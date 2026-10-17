"""The challenger Arms' rankers: reciprocal-rank fusion, dense search over chunk
embeddings and cross-encoder re-ranking, each with a fake model, the chunk embeddings
store they read, and the local embedding model, which makes no network call."""

import socket
import sqlite3

import numpy as np
import pytest

from edgar_eval.embeddings import ChunkEmbeddings, QueryEmbeddings, build_embeddings
from edgar_eval.rankers import CrossEncoderRanker, DenseRanker, HybridRanker, rrf
from edgar_rag.retrieval import Message, RankRequest, prepare_answer_context

# --- Reciprocal-rank fusion --------------------------------------------------------------


def test_rrf_scores_each_item_by_its_weighted_reciprocal_ranks():
    # a: 0.5/2 + 0.5/3; c: 0.5/4 + 0.5/2; b: 0.5/3 (k = 1, ranks from 1)
    assert rrf([["a", "b", "c"], ["c", "a"]], weights=(0.5, 0.5), k=1) == ["a", "c", "b"]


def test_rrf_weights_tilt_the_fusion_towards_one_ranking():
    assert rrf([["a", "b"], ["b", "a"]], weights=(0.8, 0.2), k=1) == ["a", "b"]
    assert rrf([["a", "b"], ["b", "a"]], weights=(0.2, 0.8), k=1) == ["b", "a"]


def test_rrf_breaks_ties_by_first_appearance():
    assert rrf([["a", "b"], ["b", "a"]], weights=(0.5, 0.5), k=1) == ["a", "b"]


def test_rrf_needs_one_weight_per_ranking():
    with pytest.raises(ValueError):
        rrf([["a"], ["b"]], weights=(1.0,), k=1)


# --- Dense search over chunk embeddings ---------------------------------------------------


class _FakeEmbedder:
    """Embeds a text as a fixed vector per keyword, so rankings are predictable."""

    model = "fake-embedding"
    price_per_million = 0.0

    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        return [self.vectors[t] if t in self.vectors else self.vectors["*"] for t in texts]


def _request(eligible, lexical=(), question="q"):
    return RankRequest(question=question, ticker="X", eligible=eligible, lexical=lexical)


def test_dense_ranking_is_by_inner_product_over_the_eligible_chunks_only():
    store = ChunkEmbeddings(
        ids=np.array([1, 2, 3, 4]),
        matrix=np.array([[1.0, 0.0], [0.6, 0.8], [0.0, 1.0], [0.99, 0.1]], dtype=np.float32),
        model="fake-embedding",
    )
    queries = QueryEmbeddings(_FakeEmbedder({"q": [0.0, 1.0]}))

    ranked = DenseRanker(store, queries)(_request(eligible=(1, 2, 3)))

    assert ranked == [3, 2, 1]  # chunk 4 is outside the hard filters


def test_dense_ranking_is_cut_to_the_candidates_the_seam_considers():
    ids = np.arange(1, 501)
    store = ChunkEmbeddings(ids=ids, matrix=np.ones((500, 2), dtype=np.float32), model="m")

    ranked = DenseRanker(store, QueryEmbeddings(_FakeEmbedder({"*": [1.0, 0.0]})), limit=200)(
        _request(eligible=tuple(int(i) for i in ids))
    )

    assert len(ranked) == 200


def test_hybrid_fuses_the_lexical_and_dense_rankings():
    store = ChunkEmbeddings(
        ids=np.array([1, 2, 3]),
        matrix=np.array([[0.0, 1.0], [0.5, 0.5], [1.0, 0.0]], dtype=np.float32),
        model="m",
    )
    dense = DenseRanker(store, QueryEmbeddings(_FakeEmbedder({"q": [1.0, 0.0]})))  # 3, 2, 1

    request = _request(eligible=(1, 2, 3), lexical=(1, 2))
    assert HybridRanker(dense, dense_weight=0.5)(request) == rrf(
        [[1, 2], [3, 2, 1]], weights=(0.5, 0.5), k=1
    )
    assert HybridRanker(dense, dense_weight=1.0)(request)[0] == 3


def test_query_embeddings_are_cached_on_disk_so_reruns_make_no_call(tmp_path):
    embedder = _FakeEmbedder({"*": [3.0, 4.0]})
    path = tmp_path / "queries.json"

    first = QueryEmbeddings(embedder, path)("What are Apple's risks?")
    again = QueryEmbeddings(embedder, path)("What are Apple's risks?")

    assert len(embedder.calls) == 1
    assert first.tolist() == again.tolist() == pytest.approx([0.6, 0.8])  # unit length


# --- The chunk embeddings store ------------------------------------------------------------


def test_build_embeddings_embeds_every_chunk_of_the_index_once(tmp_path, index):
    embedder = _FakeEmbedder({"*": [1.0, 2.0, 2.0]})
    out = tmp_path / "embeddings"

    store = build_embeddings(index, embedder, out, batch_tokens=50_000)

    (count,) = sqlite3.connect(index).execute("SELECT COUNT(*) FROM chunks").fetchone()
    assert len(store.ids) == count == sum(len(call) for call in embedder.calls)
    assert len(embedder.calls) > 1  # batched
    assert np.allclose(np.linalg.norm(store.matrix, axis=1), 1.0)
    assert ChunkEmbeddings.load(out, "fake-embedding", index).ids.tolist() == store.ids.tolist()


def test_a_stopped_build_resumes_without_embedding_the_same_batch_twice(tmp_path, index):
    class Flaky(_FakeEmbedder):
        def __call__(self, texts):
            if len(self.calls) == 2 and not getattr(self, "failed", False):
                self.failed = True
                raise RuntimeError("rate limited")
            return super().__call__(texts)

    embedder = Flaky({"*": [1.0, 0.0]})
    out = tmp_path / "embeddings"
    with pytest.raises(RuntimeError, match="rate limited"):
        build_embeddings(index, embedder, out, batch_tokens=50_000, workers=1)
    before = len(embedder.calls)

    store = build_embeddings(index, embedder, out, batch_tokens=50_000, workers=1)

    assert len(embedder.calls) > before >= 2
    # Across both runs, every chunk was embedded exactly once.
    assert sum(len(c) for c in embedder.calls) == len(store.ids)
    assert not list(out.glob("*.partial-*"))


def test_embeddings_built_from_another_index_are_refused(tmp_path, index, gap_index):
    out = tmp_path / "embeddings"
    build_embeddings(gap_index, _FakeEmbedder({"*": [1.0, 0.0]}), out)

    with pytest.raises(RuntimeError, match="make embeddings"):
        ChunkEmbeddings.load(out, "fake-embedding", index)


def test_missing_embeddings_say_how_to_build_them(tmp_path, index):
    with pytest.raises(FileNotFoundError, match="make embeddings"):
        ChunkEmbeddings.load(tmp_path, "fake-embedding", index)


# --- Cross-encoder re-ranking --------------------------------------------------------------


def test_the_cross_encoder_reorders_the_top_of_the_lexical_ranking_only(index):
    seen = []

    def score(question, texts):
        seen.append((question, len(texts)))
        return [len(t) for t in texts]  # longest first

    question = "What does Tesla say about Gigafactory Texas?"
    ranker = CrossEncoderRanker(index, score, depth=5)
    shipped = prepare_answer_context([Message("user", question)], index)
    lexical = []

    def record(request):
        lexical.extend(request.lexical)
        return ranker(request)

    reranked = prepare_answer_context([Message("user", question)], index, ranker=record)

    assert seen == [(question, 5)]
    texts = dict(sqlite3.connect(index).execute("SELECT id, text FROM chunks").fetchall())
    expected = sorted(lexical[:5], key=lambda i: -len(texts[i])) + lexical[5:]
    assert (
        ranker(_request(eligible=tuple(sorted(lexical)), lexical=tuple(lexical), question=question))
        == expected
    )
    assert {s.ticker for s in reranked.sources} == {s.ticker for s in shipped.sources}


# --- The local embedding model --------------------------------------------------------------
# The dense-local and hybrid-local Arms embed the question on this machine: under the
# one-call rule, ranking a question makes no network call. Skipped until the pinned model
# is downloaded (`make local-embeddings` downloads it).


@pytest.fixture
def no_network(monkeypatch):
    """Every socket connection and name lookup fails, as with the network unplugged."""

    def refuse(*args, **kwargs):
        raise AssertionError("a network call was made")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture(scope="module")
def local_model_cached():
    from huggingface_hub import try_to_load_from_cache

    from edgar_eval.embeddings import LOCAL_EMBEDDING_REPO, LOCAL_EMBEDDING_REVISION

    for filename in ("tokenizer.json", "onnx/model.onnx"):
        cached = try_to_load_from_cache(
            LOCAL_EMBEDDING_REPO, filename, revision=LOCAL_EMBEDDING_REVISION
        )
        if not isinstance(cached, str):
            pytest.skip("the local embedding model is not downloaded: run `make local-embeddings`")


def _chunk(index, ticker, phrase):
    db = sqlite3.connect(index)
    return db.execute(
        "SELECT id, text FROM chunks WHERE ticker = ? AND text LIKE ? ORDER BY id LIMIT 1",
        (ticker, f"%{phrase}%"),
    ).fetchone()


def test_ranking_a_question_with_the_local_model_makes_no_network_call(
    local_model_cached, index, no_network
):
    from edgar_eval.embeddings import LOCAL_EMBEDDING_MODEL, OnnxEmbedder, _unit

    chunks = [
        _chunk(index, "AAPL", "iPhone"),
        _chunk(index, "TSLA", "Gigafactory Texas"),
        _chunk(index, "JPM", "deposits"),
    ]
    embedder = OnnxEmbedder()  # loaded from the local cache, with the network refused
    store = ChunkEmbeddings(
        ids=np.array([i for i, _ in chunks]),
        matrix=_unit(np.array(embedder([t for _, t in chunks]))),
        model=LOCAL_EMBEDDING_MODEL,
    )
    dense = DenseRanker(store, QueryEmbeddings(embedder.for_queries()))
    request = _request(
        eligible=tuple(i for i, _ in chunks),
        lexical=(chunks[0][0],),
        question="Where does Tesla build vehicles at Gigafactory Texas?",
    )

    assert dense(request)[0] == chunks[1][0]
    assert set(HybridRanker(dense)(request)) == {i for i, _ in chunks}


def test_the_local_model_embeds_questions_with_its_query_instruction(local_model_cached):
    from edgar_eval.embeddings import LOCAL_QUERY_PREFIX, OnnxEmbedder

    passages = OnnxEmbedder()
    queries = passages.for_queries()
    question = "What are Apple's main risk factors?"

    (as_passage,), (as_query,) = passages([question]), queries([question])

    assert queries.session is passages.session  # one model in memory
    assert queries.prefix == LOCAL_QUERY_PREFIX and passages.prefix == ""
    assert as_passage != as_query
    assert np.linalg.norm(as_query) == pytest.approx(1.0, abs=1e-5)


def test_the_local_chunk_embeddings_are_built_with_no_network_call(
    local_model_cached, tmp_path, indexed_filings, no_network
):
    from edgar_eval.embeddings import LOCAL_EMBEDDING_MODEL, embeddings_dir, main
    from edgar_rag.retrieval import build_index

    filing = min((f for f in indexed_filings if f.ticker == "TSLA"), key=lambda f: len(f.body))
    small = build_index([filing], tmp_path / "edgar_rag.sqlite")

    assert main(["--local", "--index", str(small)]) == 0

    store = ChunkEmbeddings.load(embeddings_dir(small), LOCAL_EMBEDDING_MODEL, small)
    (count,) = sqlite3.connect(small).execute("SELECT COUNT(*) FROM chunks").fetchone()
    assert len(store.ids) == count and store.matrix.shape[1] == 384
