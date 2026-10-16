"""The retrieval Arms, all defined here. The FTS5 Arm is the Shipped Arm (ADR 0002, ADR
0008).

An Arm turns a conversation into the Answer Context it would give the Answer Call, and
ranks that context's Sources as (Filing ID, Section) pairs for the retrieval harness.
Every Arm runs the shipped retrieval seam with its own ranker in place of `bm25()`, so
each one runs inside the same Query Scope hard filters, plan, budget and deduplication,
and the generation harness can answer through any of them:

- `fts5`: `bm25()` over FTS5, as shipped.
- `dense`: OpenAI `text-embedding-3-small` embeddings of every eligible chunk, by exact
  inner product with the question's (`make embeddings` builds them).
- `hybrid`: weighted reciprocal-rank fusion (k = 1, equal weights) of the two.
- `rerank`: FTS5's top 20 re-ordered by an ONNX cross-encoder
  (`cross-encoder/ms-marco-MiniLM-L6-v2`, pinned), the rest in `bm25()` order.

The challengers' rankers are built on first use, once per index: importing this module
loads no model.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import cache
from itertools import zip_longest
from pathlib import Path

from edgar_eval.metrics import Pair
from edgar_eval.retrieval import Arm
from edgar_rag.retrieval import AnswerContext, Message, Ranker, prepare_answer_context

MakeRanker = Callable[[Path], Ranker]
"""Builds an Arm's ranker for an index."""


def source_ranking(context: AnswerContext) -> list[Pair]:
    """The Answer Context's text Sources as ranked (Filing ID, Section) pairs.

    Each Company in scope is retrieved separately with its own share of the context
    budget, and its Sources are numbered after the previous Company's. Ranking them by
    number would put the last Company's best Source behind every other Company's worst,
    so the ranking takes each Company's next-best Source in turn instead.

    Facts Sources are left out: they are Financial Facts looked up by rule, not text
    retrieved by an Arm, and the Golden Set labels Sections.
    """
    per_company: dict[str, list[Pair]] = {}
    for source in (s for s in context.sources if s.kind == "text"):
        per_company.setdefault(source.ticker, []).append((source.filing_id, source.section))
    return [
        pair for turn in zip_longest(*per_company.values()) for pair in turn if pair is not None
    ]


def seam_arm(
    name: str, description: str, make_ranker: MakeRanker | None = None, shipped: bool = False
) -> Arm:
    """An Arm that runs the retrieval seam with the ranker `make_ranker` builds for the
    index, or with `bm25()` when it is None."""

    def prepare(messages: Sequence[Message], index: Path) -> AnswerContext:
        ranker = make_ranker(Path(index)) if make_ranker else None
        return prepare_answer_context(messages, index, ranker=ranker)

    def retrieve(messages: Sequence[Message], index: Path) -> list[Pair]:
        return source_ranking(prepare(messages, index))

    return Arm(name, description, retrieve, shipped=shipped, prepare=prepare)


@cache
def _dense(index: Path):
    from edgar_eval.embeddings import (
        DEFAULT_EMBEDDING_MODEL,
        ChunkEmbeddings,
        OpenAIEmbedder,
        QueryEmbeddings,
        embeddings_dir,
    )
    from edgar_eval.rankers import DenseRanker

    directory = embeddings_dir(index)
    store = ChunkEmbeddings.load(directory, DEFAULT_EMBEDDING_MODEL, index)
    queries = QueryEmbeddings(
        OpenAIEmbedder(DEFAULT_EMBEDDING_MODEL),
        directory / f"queries-{DEFAULT_EMBEDDING_MODEL}.json",
    )
    return DenseRanker(store, queries)


@cache
def _hybrid(index: Path):
    from edgar_eval.rankers import HybridRanker

    return HybridRanker(_dense(index), dense_weight=0.5, k=1)


@cache
def _rerank(index: Path):
    from edgar_eval.rankers import CrossEncoderRanker, OnnxCrossEncoder

    return CrossEncoderRanker(index, OnnxCrossEncoder(), depth=20)


ARMS: tuple[Arm, ...] = (
    seam_arm(
        "fts5",
        "SQLite FTS5 bm25() within each Company's hard filter (ADR 0002)",
        shipped=True,
    ),
    seam_arm(
        "dense",
        "OpenAI text-embedding-3-small, exact inner product over the filtered chunks",
        _dense,
    ),
    seam_arm(
        "hybrid",
        "Weighted reciprocal-rank fusion (k = 1, equal weights) of FTS5 and dense",
        _hybrid,
    ),
    seam_arm(
        "rerank",
        "FTS5 top 20 re-ranked by an ONNX cross-encoder (ms-marco-MiniLM-L6-v2)",
        _rerank,
    ),
)
