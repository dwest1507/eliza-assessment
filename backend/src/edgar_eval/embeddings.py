"""Chunk embeddings for the dense and hybrid Arms: built once from the index, stored
beside it as a matrix, and searched by exact inner product over the filtered rows
(ADR 0002).

- `build_embeddings` embeds every chunk of the index with an embedding model and writes
  `<model>.npy` (one unit-length row per chunk, in chunk id order) and `<model>.json`
  (the model, the chunk count and a fingerprint of the index's chunks) to
  `data/derived/embeddings/`. Embeddings built from a different index are refused when
  loaded, so a rebuilt index never meets stale vectors.
- `QueryEmbeddings` embeds a question, caching each vector on disk by its text, so a
  rerun of the harnesses makes no embedding call.

`make embeddings` runs it over the whole index with OpenAI's `text-embedding-3-small`.
It needs `OPENAI_API_KEY` and costs about $0.35 (17.4 million tokens). Those vectors are
the `dense` and `hybrid` Arms', which embed each question with OpenAI too: a second API
call per question, so under the one-call rule they can't ship.

`make local-embeddings` (`--local`) runs it with `OnnxEmbedder` instead: the local
`BAAI/bge-small-en-v1.5`, pinned to a commit and run by ONNX Runtime on the CPU, for the
`dense-local` and `hybrid-local` Arms, which embed the question with the same model. It
makes no API call and costs nothing; the whole index takes about 30 minutes.

    python -m edgar_eval.embeddings [--index PATH] [--model MODEL | --local]

This module needs numpy (and, for the local model, ONNX Runtime, `tokenizers` and
`huggingface-hub`), which are in the backend's dev dependency group only: the product
never loads them.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from edgar_rag.retrieval import DEFAULT_INDEX

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "LOCAL_EMBEDDING_MODEL",
    "LOCAL_EMBEDDING_REPO",
    "LOCAL_EMBEDDING_REVISION",
    "ChunkEmbeddings",
    "Embedder",
    "OnnxEmbedder",
    "OpenAIEmbedder",
    "QueryEmbeddings",
    "build_embeddings",
    "embeddings_dir",
]

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

LOCAL_EMBEDDING_MODEL = "bge-small-en-v1.5"
"""The local embedding model of the `dense-local` and `hybrid-local` Arms, as its
embeddings' file names give it."""
LOCAL_EMBEDDING_REPO = "BAAI/bge-small-en-v1.5"
LOCAL_EMBEDDING_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
"""The Hugging Face commit the local embedding model is pinned to, never a branch."""
LOCAL_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
"""What the model's card says to put before a question (never before a passage)."""

EMBEDDING_PRICES = {"text-embedding-3-small": 0.02, "text-embedding-3-large": 0.13}
"""US dollars per million input tokens, OpenAI's standard tier."""


class Embedder(Protocol):
    """An embedding model: texts in, one vector per text out, in order."""

    @property
    def model(self) -> str: ...

    def __call__(self, texts: Sequence[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    """OpenAI's embeddings endpoint. Reads `OPENAI_API_KEY` from the environment."""

    def __init__(self, model: str = DEFAULT_EMBEDDING_MODEL):
        self.model = model
        self._client = None

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        if self._client is None:  # only when a call is needed, so cached queries need no key
            from openai import OpenAI

            self._client = OpenAI(max_retries=10)
        response = self._client.embeddings.create(model=self.model, input=list(texts))
        return [item.embedding for item in sorted(response.data, key=lambda d: d.index)]


class OnnxEmbedder:
    """A local embedding model run by ONNX Runtime on the CPU: no API call. It is
    downloaded once from Hugging Face at a pinned revision and read from the local cache
    after that, so loading it makes no network call either once it is there. A text is
    embedded as the model's CLS token, truncated to its 512 tokens (a long chunk is
    embedded on its opening); `prefix` goes before every text (`for_queries` gives the
    question's). Texts run `batch_size` at a time on `threads` CPU threads (ONNX
    Runtime's default when None): on 512-token chunks one at a time is fastest, and
    two callers at once with 8 threads each beat one with 16."""

    def __init__(
        self,
        repo: str = LOCAL_EMBEDDING_REPO,
        revision: str = LOCAL_EMBEDDING_REVISION,
        model: str = LOCAL_EMBEDDING_MODEL,
        *,
        prefix: str = "",
        max_length: int = 512,
        batch_size: int = 1,
        threads: int | None = None,
    ):
        import onnxruntime
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(_hub_file(repo, "tokenizer.json", revision))
        tokenizer.enable_truncation(max_length=max_length)
        tokenizer.enable_padding()
        self.tokenizer = tokenizer
        options = onnxruntime.SessionOptions()
        if threads:
            options.intra_op_num_threads = threads
        self.session = onnxruntime.InferenceSession(
            _hub_file(repo, "onnx/model.onnx", revision),
            options,
            providers=["CPUExecutionProvider"],
        )
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.model = model
        self.prefix = prefix
        self.batch_size = batch_size

    def for_queries(self, prefix: str = LOCAL_QUERY_PREFIX) -> OnnxEmbedder:
        """The same model, sharing its session, putting `prefix` before every text."""
        queries = copy.copy(self)
        queries.prefix = prefix
        return queries

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [self.prefix + t for t in texts[start : start + self.batch_size]]
            encoded = self.tokenizer.encode_batch(batch)
            feed = {
                "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
                "token_type_ids": np.array([e.type_ids for e in encoded], dtype=np.int64),
            }
            (hidden,) = self.session.run(None, {k: v for k, v in feed.items() if k in self.inputs})
            vectors += _unit(hidden[:, 0]).tolist()  # the CLS token
        return vectors


def _hub_file(repo: str, filename: str, revision: str) -> str:
    """A model file at a pinned revision: from the local cache when it is there, with no
    network call, and downloaded into it otherwise."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        return hf_hub_download(repo, filename, revision=revision, local_files_only=True)
    except LocalEntryNotFoundError:
        return hf_hub_download(repo, filename, revision=revision)


def embeddings_dir(index: str | Path) -> Path:
    """Where an index's embeddings live: beside it."""
    return Path(index).parent / "embeddings"


def _unit(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return (matrix / np.where(norms == 0, 1, norms)).astype(np.float32)


def _chunks(index: str | Path) -> list[tuple[int, int, str]]:
    db = sqlite3.connect(f"{Path(index).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return db.execute("SELECT id, tokens, text FROM chunks ORDER BY id").fetchall()
    finally:
        db.close()


def fingerprint(index: str | Path) -> str:
    """A hash of every chunk's id and text: equal only for indexes with the same chunks."""
    digest = hashlib.sha256()
    for chunk_id, _, text in _chunks(index):
        digest.update(f"{chunk_id}\0{text}\0".encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class ChunkEmbeddings:
    """One unit-length vector per chunk, row `i` for chunk `ids[i]` (ascending)."""

    ids: np.ndarray
    matrix: np.ndarray
    model: str

    def rows(self, chunk_ids: Sequence[int]) -> np.ndarray:
        """The vectors of these chunks, in the order given."""
        positions = np.searchsorted(self.ids, np.asarray(chunk_ids, dtype=self.ids.dtype))
        return self.matrix[positions]

    @classmethod
    def load(cls, directory: str | Path, model: str, index: str | Path) -> ChunkEmbeddings:
        """The embeddings of `index` built with `model`, refusing any built from another
        index."""
        directory = Path(directory)
        meta_path, matrix_path = directory / f"{model}.json", directory / f"{model}.npy"
        if not meta_path.exists() or not matrix_path.exists():
            raise FileNotFoundError(
                f"no {model} embeddings in {directory}; build them with `make embeddings`"
            )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta["fingerprint"] != fingerprint(index):
            raise RuntimeError(
                f"the {model} embeddings in {directory} were built from another index; "
                "rebuild them with `make embeddings`"
            )
        return cls(
            ids=np.asarray(meta["ids"], dtype=np.int64),
            matrix=np.load(matrix_path, mmap_mode="r"),
            model=model,
        )


def build_embeddings(
    index: str | Path,
    embedder: Embedder,
    directory: str | Path,
    *,
    batch_tokens: int = 150_000,
    batch_size: int = 512,
    workers: int = 8,
    tokens_per_minute: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ChunkEmbeddings:
    """Embed every chunk of the index and write the matrix and its metadata.

    Chunks are sent in batches of at most `batch_size` texts and about `batch_tokens`
    tokens (the index's own token estimates), `workers` batches at a time. Each batch
    is saved as it comes back, so a run stopped by an error or a rate limit resumes
    where it stopped; the matrix is written once every batch is in. With
    `tokens_per_minute`, batches are held back so that no more than that many
    (estimated) tokens are sent in any minute.
    """
    chunks = _chunks(index)
    print_ = fingerprint(index)
    directory = Path(directory)
    partial = directory / f"{embedder.model}.partial-{print_[:16]}"
    partial.mkdir(parents=True, exist_ok=True)
    batches: list[list[tuple[int, int, str]]] = [[]]
    spent = 0
    for chunk in chunks:
        if batches[-1] and (len(batches[-1]) >= batch_size or spent + chunk[1] > batch_tokens):
            batches.append([])
            spent = 0
        batches[-1].append(chunk)
        spent += chunk[1]
    done = 0
    lock = threading.Lock()
    sent: list[tuple[float, int]] = []  # (time, estimated tokens) of the last minute

    def wait_for_budget(tokens: int) -> None:
        if tokens_per_minute is None:
            return
        while True:
            with lock:
                now = time.monotonic()
                sent[:] = [(t, n) for t, n in sent if now - t < 60]
                if not sent or sum(n for _, n in sent) + tokens <= tokens_per_minute:
                    sent.append((now, tokens))
                    return
                wait = 60 - (now - sent[0][0])
            time.sleep(max(wait, 0.1))

    def embed(numbered: tuple[int, list[tuple[int, int, str]]]) -> np.ndarray:
        nonlocal done
        number, batch = numbered
        saved = partial / f"batch-{number:05d}-{len(batch)}.npy"
        if saved.exists():
            vectors = np.load(saved)
        else:
            wait_for_budget(sum(tokens for _, tokens, _ in batch))
            vectors = np.array(embedder([text for _, _, text in batch]), dtype=np.float32)
            if len(vectors) != len(batch):
                raise RuntimeError(f"asked for {len(batch)} embeddings, got {len(vectors)}")
            np.save(saved, vectors)
        with lock:
            done += 1
            if progress:
                progress(done, len(batches))
        return vectors

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        parts = list(pool.map(embed, enumerate(b for b in batches if b)))
    ids = np.array([chunk_id for chunk_id, _, _ in chunks], dtype=np.int64)
    matrix = _unit(np.concatenate(parts) if parts else np.zeros((0, 0), dtype=np.float32))
    np.save(directory / f"{embedder.model}.npy", matrix)
    meta = {
        "model": embedder.model,
        "chunks": len(ids),
        "dimensions": int(matrix.shape[1]) if len(matrix) else 0,
        "tokens": sum(tokens for _, tokens, _ in chunks),
        "fingerprint": print_,
        "ids": ids.tolist(),
    }
    (directory / f"{embedder.model}.json").write_text(json.dumps(meta) + "\n", encoding="utf-8")
    shutil.rmtree(partial)
    return ChunkEmbeddings(ids=ids, matrix=matrix, model=embedder.model)


class QueryEmbeddings:
    """A question's unit-length embedding, cached by its text (on disk when `path` is
    given), so the same question is embedded once."""

    def __init__(self, embedder: Embedder, path: str | Path | None = None):
        self.embedder = embedder
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._cache: dict[str, list[float]] = {}
        if self.path and self.path.exists():
            self._cache = json.loads(self.path.read_text(encoding="utf-8"))

    @property
    def model(self) -> str:
        return self.embedder.model

    def __call__(self, text: str) -> np.ndarray:
        with self._lock:
            vector = self._cache.get(text)
        if vector is None:
            (vector,) = self.embedder([text])
            with self._lock:
                self._cache[text] = vector
                if self.path:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self.path.write_text(json.dumps(self._cache) + "\n", encoding="utf-8")
        return _unit(np.asarray(vector, dtype=np.float32))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed every chunk of the index.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument(
        "--local",
        action="store_true",
        help=f"embed with the local {LOCAL_EMBEDDING_MODEL} instead: no API call, no cost",
    )
    args = parser.parse_args(argv)
    directory = embeddings_dir(args.index)

    def progress(done: int, total: int) -> None:
        if done == total or done % 20 == 0:
            print(f"  {done}/{total} batches embedded", flush=True)

    if args.local:
        # On the CPU, about 30 chunks a second: the whole index takes about 30 minutes.
        store = build_embeddings(
            args.index,
            OnnxEmbedder(threads=8),
            directory,
            batch_tokens=10**9,
            batch_size=64,
            workers=2,
            progress=progress,
        )
        print(f"{len(store.ids)} chunk embeddings written to {directory / (store.model + '.npy')}")
        return 0

    # The index's token estimates run a few percent under OpenAI's count, so pacing at
    # 700k estimated tokens a minute stays under a 1M tokens-per-minute rate limit. The
    # whole index takes about 25 minutes.
    store = build_embeddings(
        args.index,
        OpenAIEmbedder(args.model),
        directory,
        batch_tokens=100_000,
        workers=2,
        tokens_per_minute=700_000,
        progress=progress,
    )
    print(f"{len(store.ids)} chunk embeddings written to {directory / (args.model + '.npy')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
