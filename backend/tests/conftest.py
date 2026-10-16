"""Shared fixtures: an index built from real Corpus Filings."""

import pytest

from edgar_rag.corpus import load_corpus
from edgar_rag.retrieval import build_index

# The brief's first example names Apple, Tesla and JPMorgan (a Snapshot Company).
# Target is a Company whose name is also an everyday word.
INDEXED_TICKERS = {"AAPL", "TSLA", "JPM", "TGT"}


@pytest.fixture(scope="session")
def indexed_filings():
    return [f for f in load_corpus() if f.ticker in INDEXED_TICKERS]


@pytest.fixture(scope="session")
def index(tmp_path_factory, indexed_filings):
    return build_index(indexed_filings, tmp_path_factory.mktemp("index") / "edgar_rag.sqlite")
