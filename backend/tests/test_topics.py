"""The topic table: each added search term is the Filings' own wording, found in the
Corpus, and none is copied from a Golden Set or Brief Suite evidence quote.

The retrieval behaviour (a topic phrase's terms bring in a passage the question's own
words miss, and a question with no topic phrase searches exactly as before) is tested
through the retrieval seam in `test_retrieval.py`.
"""

import re
import sqlite3

import pytest

from edgar_rag._topics import TOPICS, added_terms
from edgar_rag.golden_set import (
    GOLDEN_SET_V1,
    GOLDEN_SET_V2,
    load_brief_suite,
    load_golden_set,
    normalise_whitespace,
)
from edgar_rag.retrieval import DEFAULT_INDEX

WORDINGS = [(topic.name, w) for topic in TOPICS for w in topic.wording]


def _evidence_quotes():
    sets = (load_golden_set(GOLDEN_SET_V1), load_golden_set(GOLDEN_SET_V2), load_brief_suite())
    return [
        normalise_whitespace(f.evidence).lower()
        for golden in sets
        for case in golden.cases
        for f in case.required_facts
    ]


def _full_index():
    if not DEFAULT_INDEX.exists():
        pytest.skip("no full index: run `make index`")
    db = sqlite3.connect(DEFAULT_INDEX)
    db.row_factory = sqlite3.Row
    return db


def test_the_table_covers_the_topics_and_every_entry_names_its_filing_phrase():
    assert {t.name for t in TOPICS} == {
        "drug-pricing regulation",
        "supply chain",
        "competition",
        "cybersecurity",
    }
    for _, wording in WORDINGS:
        # A term is a short run of words, safe to quote for FTS5 `MATCH`.
        assert re.fullmatch(r"[A-Za-z0-9]+(?: [A-Za-z0-9]+){0,3}", wording.term)
        assert wording.term.lower() in wording.phrase.lower()
        assert wording.filing_id


@pytest.mark.parametrize(("topic", "wording"), WORDINGS, ids=lambda x: getattr(x, "term", x))
def test_every_added_term_and_its_phrase_are_in_the_corpus(topic, wording):
    db = _full_index()
    matches = db.execute(
        "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?", (f'"{wording.term}"',)
    ).fetchone()[0]
    assert matches >= 1, f"{topic}: {wording.term!r} matches no chunk"
    texts = [
        normalise_whitespace(row["text"])
        for row in db.execute(
            "SELECT text FROM filing_chunks WHERE filing_id = ?", (wording.filing_id,)
        )
    ]
    assert any(normalise_whitespace(wording.phrase) in t for t in texts), (
        f"{topic}: the phrase for {wording.term!r} is not in {wording.filing_id}"
    )


def test_no_added_term_or_its_phrase_is_copied_from_an_evidence_quote():
    quotes = _evidence_quotes()
    copied = [
        (topic, w.term)
        for topic, w in WORDINGS
        for quote in quotes
        # A term that is a whole quote, or a justifying phrase taken from one.
        if w.term.lower() == quote
        or normalise_whitespace(w.phrase).lower() in quote
        or quote in normalise_whitespace(w.phrase).lower()
    ]
    assert copied == []


@pytest.mark.parametrize(
    ("question", "sector", "topic"),
    [
        ("What regulatory risks does Pfizer face?", "Health Care", "drug-pricing regulation"),
        ("What do the big drugmakers say about drug pricing?", "Health Care", None),
        ("How exposed is Apple to supply chain disruptions?", "Information Technology", None),
        ("Who are Target's main competitors?", "Consumer Staples", "competition"),
        ("How do their cybersecurity risks compare?", "Financials", "cybersecurity"),
    ],
)
def test_a_topic_phrase_adds_its_terms(question, sector, topic):
    terms = added_terms(question, sector)

    assert terms
    if topic is not None:
        named = next(t for t in TOPICS if t.name == topic)
        assert set(terms) >= {w.term for w in named.wording}


def test_drug_pricing_terms_are_added_only_for_health_care_companies():
    question = "What regulatory risks does JPMorgan face?"

    assert added_terms(question, "Financials") == ()
    assert added_terms(question, None) == ()
    assert "Inflation Reduction Act" in added_terms(question, "Health Care")


@pytest.mark.parametrize(
    "question",
    [
        "What are the primary risk factors facing Apple, Tesla, and JPMorgan?",
        "How has NVIDIA's revenue changed over the last two years?",
        "What legal proceedings is Apple involved in?",
        "What is the growth outlook for Microsoft's cloud business?",
    ],
)
def test_a_question_with_no_topic_phrase_adds_nothing(question):
    for sector in ("Health Care", "Information Technology", None):
        assert added_terms(question, sector) == ()
