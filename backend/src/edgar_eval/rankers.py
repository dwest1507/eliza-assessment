"""The challenger Arms' rankers. Each replaces `bm25()` inside the retrieval seam's hard
filters (`edgar_rag.retrieval.Ranker`), so a challenger is measured on exactly the
pipeline the product runs: the same Query Scope, plan, budget and deduplication.

- `DenseRanker`: every eligible chunk by the inner product of its embedding with the
  question's, best first.
- `HybridRanker`: weighted reciprocal-rank fusion of the `bm25()` ranking and the dense
  one.
- `CrossEncoderRanker`: the top of the `bm25()` ranking re-scored by a cross-encoder,
  the rest left in `bm25()` order.

`OnnxCrossEncoder` runs a cross-encoder pinned to an exact Hugging Face revision with
ONNX Runtime. numpy, ONNX Runtime, `tokenizers` and `huggingface-hub` are in the
backend's dev dependency group only: the product never loads them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Hashable, Sequence
from pathlib import Path

import numpy as np

from edgar_eval.embeddings import ChunkEmbeddings, QueryEmbeddings
from edgar_rag.retrieval import RankRequest

__all__ = [
    "CANDIDATES",
    "CROSS_ENCODER",
    "CROSS_ENCODER_REVISION",
    "CrossEncoderRanker",
    "DenseRanker",
    "HybridRanker",
    "OnnxCrossEncoder",
    "rrf",
]

CANDIDATES = 200
"""How many ranked chunks a ranker hands back: as many as the shipped seam considers."""


def rrf[T: Hashable](
    rankings: Sequence[Sequence[T]], weights: Sequence[float], k: float = 1
) -> list[T]:
    """Weighted reciprocal-rank fusion: each item scores the sum over rankings of
    `weight / (k + rank)`, ranks counted from 1, best first. Ties keep the order in
    which items first appear."""
    if len(rankings) != len(weights):
        raise ValueError("rrf needs one weight per ranking")
    scores: dict[T, float] = {}
    for ranking, weight in zip(rankings, weights, strict=True):
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + weight / (k + rank)
    order = {item: n for n, item in enumerate(scores)}
    return sorted(scores, key=lambda item: (-scores[item], order[item]))


class DenseRanker:
    """Exact inner-product search over the eligible chunks' embeddings."""

    def __init__(self, store: ChunkEmbeddings, queries: QueryEmbeddings, limit: int = CANDIDATES):
        self.store = store
        self.queries = queries
        self.limit = limit

    def __call__(self, request: RankRequest) -> list[int]:
        if not request.eligible:
            return []
        scores = self.store.rows(request.eligible) @ self.queries(request.question)
        best = np.argsort(-scores, kind="stable")[: self.limit]
        return [request.eligible[i] for i in best]


class HybridRanker:
    """Weighted reciprocal-rank fusion of the `bm25()` and dense rankings."""

    def __init__(
        self, dense: DenseRanker, dense_weight: float = 0.5, k: float = 1, limit: int = CANDIDATES
    ):
        self.dense = dense
        self.dense_weight = dense_weight
        self.k = k
        self.limit = limit

    def __call__(self, request: RankRequest) -> list[int]:
        fused = rrf(
            [request.lexical, self.dense(request)],
            weights=(1 - self.dense_weight, self.dense_weight),
            k=self.k,
        )
        return fused[: self.limit]


Scorer = Callable[[str, Sequence[str]], Sequence[float]]
"""A cross-encoder: the question and passages in, one relevance score per passage out."""


class CrossEncoderRanker:
    """The first `depth` chunks of the `bm25()` ranking, re-ordered by a cross-encoder's
    score; the rest follow in `bm25()` order."""

    def __init__(self, index: str | Path, score: Scorer, depth: int = 20):
        self.index = Path(index)
        self.score = score
        self.depth = depth

    def __call__(self, request: RankRequest) -> list[int]:
        top, rest = list(request.lexical[: self.depth]), list(request.lexical[self.depth :])
        if not top:
            return rest
        db = sqlite3.connect(f"{self.index.resolve().as_uri()}?mode=ro", uri=True)
        try:
            texts = dict(
                db.execute(
                    f"SELECT id, text FROM chunks WHERE id IN ({', '.join('?' * len(top))})", top
                ).fetchall()
            )
        finally:
            db.close()
        scores = self.score(request.question, [texts[i] for i in top])
        order = sorted(range(len(top)), key=lambda n: -scores[n])
        return [top[n] for n in order] + rest


CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L6-v2"
CROSS_ENCODER_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
"""The Hugging Face commit the cross-encoder is pinned to, never a branch."""


class OnnxCrossEncoder:
    """A cross-encoder run by ONNX Runtime on the CPU, downloaded once from Hugging Face
    at a pinned revision. Question and passage are truncated together to the model's
    512 tokens, so a long chunk is scored on its opening."""

    def __init__(
        self,
        repo: str = CROSS_ENCODER,
        revision: str = CROSS_ENCODER_REVISION,
        max_length: int = 512,
        batch_size: int = 16,
    ):
        import onnxruntime
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(hf_hub_download(repo, "tokenizer.json", revision=revision))
        tokenizer.enable_truncation(max_length=max_length, strategy="longest_first")
        tokenizer.enable_padding()
        self.tokenizer = tokenizer
        self.session = onnxruntime.InferenceSession(
            hf_hub_download(repo, "onnx/model.onnx", revision=revision),
            providers=["CPUExecutionProvider"],
        )
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.batch_size = batch_size

    def __call__(self, question: str, passages: Sequence[str]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(passages), self.batch_size):
            batch = passages[start : start + self.batch_size]
            encoded = self.tokenizer.encode_batch([(question, p) for p in batch])
            feed = {
                "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
                "token_type_ids": np.array([e.type_ids for e in encoded], dtype=np.int64),
            }
            (logits,) = self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})
            scores += [float(row[0]) for row in logits]
        return scores
