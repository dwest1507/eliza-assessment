"""Shared fixtures: an index built from real Corpus Filings."""

from datetime import date

import pytest

from edgar_rag.corpus import load_corpus
from edgar_rag.retrieval import build_index


@pytest.fixture(autouse=True)
def _default_answer_model(monkeypatch):
    """Every test starts on the default answer model, whatever `ANSWER_MODEL` a developer's
    shell or `backend/.env` (which the Makefile exports) sets; a test sets it itself."""
    monkeypatch.delenv("ANSWER_MODEL", raising=False)


# The brief's first example names Apple, Tesla and JPMorgan (a Snapshot Company).
# Target is a Company whose name is also an everyday word. NVIDIA's fiscal year ends in
# January, and its 10-Qs state risk text rather than pointing back to the 10-K.
INDEXED_TICKERS = {"AAPL", "TSLA", "JPM", "TGT", "NVDA"}


@pytest.fixture(scope="session")
def indexed_filings():
    return [f for f in load_corpus() if f.ticker in INDEXED_TICKERS]


@pytest.fixture(scope="session")
def index(tmp_path_factory, indexed_filings):
    return build_index(indexed_filings, tmp_path_factory.mktemp("index") / "edgar_rag.sqlite")


# The Companies of the brief's sector example and the other Sector phrases of assumption 5,
# with the neighbours each phrase must leave out: Thermo Fisher and UnitedHealth (Health
# Care, not pharmaceutical) and Goldman Sachs and Morgan Stanley (Capital Markets, not
# Banks). Only Filings from mid-2024 on, which hold every Company's latest 10-K.
SECTOR_TICKERS = {
    *("JNJ", "LLY", "MRK", "PFE", "ABBV", "TMO", "UNH"),
    *("BAC", "JPM", "GS", "MS"),
    *("CVX", "XOM"),
}


@pytest.fixture(scope="session")
def sector_index(tmp_path_factory):
    since = date(2024, 6, 30)
    filings = [f for f in load_corpus() if f.ticker in SECTOR_TICKERS and f.report_period >= since]
    return build_index(filings, tmp_path_factory.mktemp("sector_index") / "edgar_rag.sqlite")


# The Companies of "Compare Coke and Pepsi", an Overview route question: Coca-Cola, whose
# latest MD&A is in a 10-Q after its latest 10-K, and PepsiCo, whose latest Filing is its
# 10-K. Only Filings from mid-2024 on, which hold both latest 10-Ks.
OVERVIEW_TICKERS = {"KO", "PEP"}


@pytest.fixture(scope="session")
def overview_index(tmp_path_factory):
    since = date(2024, 6, 30)
    filings = [
        f for f in load_corpus() if f.ticker in OVERVIEW_TICKERS and f.report_period >= since
    ]
    return build_index(filings, tmp_path_factory.mktemp("overview_index") / "edgar_rag.sqlite")


# The Coverage Gap Companies the shared index leaves out: General Electric, whose only
# Filing is GE Capital's FY2014 10-K (a stale Filing of a different legal entity), and
# Bank of America, a Snapshot Company that a missing peer (Wells Fargo) is compared with.
GAP_TICKERS = {"GE", "BAC"}


@pytest.fixture(scope="session")
def gap_index(tmp_path_factory):
    filings = [f for f in load_corpus() if f.ticker in GAP_TICKERS]
    return build_index(filings, tmp_path_factory.mktemp("gap_index") / "edgar_rag.sqlite")


@pytest.fixture
def golden_set_v2_file(tmp_path):
    """Writes a Golden Set version 2 file of version 1 cases rewritten with their ids, a
    tier on every fact and the split given for each: `make({"risk-unh-cybersecurity":
    "dev"})`."""
    import json

    from edgar_rag.golden_set import GOLDEN_SET_V1, SPLIT_RULE_V2

    def make(splits):
        version_1 = json.loads(GOLDEN_SET_V1.read_text(encoding="utf-8"))["cases"]
        cases = []
        for case in (c for c in version_1 if c["id"] in splits):
            for fact in case["required_facts"]:
                fact["tier"] = "must_state"
            cases.append(case | {"split": splits[case["id"]]})
        path = tmp_path / "golden_set_v2.json"
        data = {"version": 2, "split_rule": SPLIT_RULE_V2, "cases": cases}
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return make
