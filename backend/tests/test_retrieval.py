"""Tests through the retrieval seam: build an index from real Corpus Filings, then
prepare Answer Contexts from conversations."""

import re
import sqlite3

import pytest

from edgar_rag import _topics
from edgar_rag.corpus import filing_months
from edgar_rag.retrieval import (
    CHUNK_TOKENS,
    CONTEXT_BUDGET_TOKENS,
    NEAR_DUPLICATE,
    PROMPT_VERSION,
    STUB_TOKENS,
    Message,
    build_index,
    count_tokens,
    index_chunk_tokens,
    prepare_answer_context,
)

BRIEF_QUESTION = (
    "What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?"
)


def _chunks(index, **where):
    """Every chunk of every Filing, one row per Filing a chunk appears in."""
    db = sqlite3.connect(index)
    db.row_factory = sqlite3.Row
    clause = " AND ".join(f"{k} = ?" for k in where) or "1"
    rows = db.execute(
        f"SELECT * FROM filing_chunks WHERE {clause} ORDER BY filing_id, ordinal",
        tuple(where.values()),
    ).fetchall()
    db.close()
    return rows


def _filing(filings, filing_id):
    return next(f for f in filings if f.filing_id == filing_id)


def _ask(index, question):
    return prepare_answer_context([Message("user", question)], index)


# --- Building the index ----------------------------------------------------------------


def test_build_index_writes_one_sqlite_file_with_every_filing(index, indexed_filings):
    assert index.exists()
    indexed = {row["filing_id"] for row in _chunks(index)}
    assert indexed == {f.filing_id for f in indexed_filings}
    assert not list(index.parent.glob("*.partial"))


def test_build_index_replaces_an_existing_index(tmp_path, indexed_filings):
    path = tmp_path / "edgar_rag.sqlite"
    path.write_text("not an index")
    jpm = [f for f in indexed_filings if f.ticker == "JPM"]

    build_index(jpm, path)

    assert {row["ticker"] for row in _chunks(path)} == {"JPM"}


def test_table_of_contents_is_left_out(index, indexed_filings):
    filing = _filing(indexed_filings, "AAPL_10-K_2024-09-28")
    toc_rows = [
        row
        for row in filing.body[filing.toc.start : filing.toc.end].split("\n")
        if "Risk Factors" in row or "Legal Proceedings" in row
    ]
    assert toc_rows  # e.g. "Item 1A. | Risk Factors | 5"

    texts = [c["text"] for c in _chunks(index, filing_id=filing.filing_id)]
    assert not any(row in text for row in toc_rows for text in texts)


def test_exhibit_index_is_left_out(index, indexed_filings):
    filing = _filing(indexed_filings, "AAPL_10-K_2024-09-28")
    exhibit_rows = [
        line for line in filing.body.split("\n") if re.match(r"\s*\|?\s*31\.1\**\s*\|", line)
    ]
    assert exhibit_rows  # the CEO certification's row in the exhibit index

    texts = [c["text"] for c in _chunks(index, filing_id=filing.filing_id)]
    assert not any(row in text for row in exhibit_rows for text in texts)
    assert not any("Rule 13a-14(a)" in line for text in texts for line in text.split("\n"))


def test_signatures_are_left_out(index):
    texts = [c["text"] for c in _chunks(index)]

    assert not any(re.search(r"duly\s+caused\s+this", t, re.I) for t in texts)
    assert not any(re.search(r"signed\s+below\s+by\s+the\s+following", t, re.I) for t in texts)
    assert not any("/s/ Timothy D. Cook" in re.sub(r"\s+", " ", t) for t in texts)
    assert not any("/s/ Elon Musk" in t for t in texts)


def test_page_furniture_is_stripped(index):
    texts = [c["text"] for c in _chunks(index)]

    assert not any(re.search("Table of Contents", t, re.I) for t in texts)
    # Apple's page footer, glued into its prose: "Apple Inc. | 2024 Form 10-K | 21".
    assert not any(re.search(r"Form 10-[KQ] \| \d", t) for t in texts)
    assert not any(re.fullmatch(r"\s*\d{1,3}\s*", line) for t in texts for line in t.split("\n"))


def test_every_chunk_carries_the_filing_metadata(index):
    chunk = next(
        c
        for c in _chunks(index, filing_id="AAPL_10-K_2024-09-28", section="Risk Factors")
        if "global and regional economic conditions" in c["text"]
    )

    assert dict(chunk) | {
        "id": None,
        "ordinal": None,
        "tokens": None,
        "text": None,
        "new_text": None,
    } == {
        "id": None,
        "filing_id": "AAPL_10-K_2024-09-28",
        "ticker": "AAPL",
        "company": "Apple Inc",
        "sector": "Information Technology",
        "industry": "Technology Hardware, Storage & Peripherals",
        "form_type": "10-K",
        "report_period": "2024-09-28",
        "fiscal_period": "FY2024",
        "coverage": "tracked",
        "section": "Risk Factors",
        "item": "Item 1A",
        "kind": "prose",
        "ordinal": None,
        "tokens": None,
        "text": None,
        "new_text": None,
    }


def test_no_chunk_is_missing_metadata(index):
    chunks = _chunks(index)
    required = (
        "filing_id",
        "ticker",
        "company",
        "sector",
        "industry",
        "form_type",
        "report_period",
        "fiscal_period",
        "coverage",
        "section",
        "kind",
    )

    assert all(c[field] for c in chunks for field in required)
    assert all(c["item"] or c["section"] == "Unsectioned" for c in chunks)
    assert {c["kind"] for c in chunks} == {"prose", "table", "risk_pointer"}
    assert {c["coverage"] for c in chunks if c["ticker"] == "JPM"} == {"snapshot"}


def test_chunks_stay_inside_their_section_and_within_the_size_limit(index, indexed_filings):
    filing = _filing(indexed_filings, "TSLA_10-K_2024-12-31")
    sections = {(s.name, s.item): s.text for s in filing.sections}

    chunks = _chunks(index, filing_id=filing.filing_id)

    for chunk in chunks:
        section_text = sections[(chunk["section"], chunk["item"])]
        first_line = chunk["text"].split("\n")[0][:40]
        assert first_line in section_text, (chunk["section"], first_line)
        assert count_tokens(chunk["text"]) <= 800
    prose = [count_tokens(c["text"]) for c in chunks if c["kind"] == "prose"]
    assert sorted(prose)[len(prose) // 2] >= 500  # most prose chunks are 500–800 tokens


def test_the_index_records_its_chunk_size(index):
    assert index_chunk_tokens(index) == CHUNK_TOKENS == 600


def test_an_index_can_be_built_with_another_chunk_size(tmp_path, indexed_filings):
    filing = _filing(indexed_filings, "AAPL_10-K_2024-09-28")

    small = build_index([filing], tmp_path / "small.sqlite", chunk_tokens=300)
    default = build_index([filing], tmp_path / "default.sqlite")

    assert index_chunk_tokens(small) == 300
    chunks = _chunks(small)
    assert all(count_tokens(c["text"]) <= 400 for c in chunks)  # four thirds of the target
    prose = [count_tokens(c["text"]) for c in chunks if c["kind"] == "prose"]
    assert 250 <= sorted(prose)[len(prose) // 2] <= 400
    assert len(chunks) > len(_chunks(default))


def test_consecutive_prose_chunks_overlap(index):
    chunks = _chunks(index, filing_id="TSLA_10-K_2024-12-31", section="Risk Factors")
    pairs = [
        (a, b)
        for a, b in zip(chunks, chunks[1:], strict=False)
        if a["kind"] == b["kind"] == "prose" and b["ordinal"] == a["ordinal"] + 1
    ]

    assert len(pairs) > 10
    assert all(b["text"][:40] in a["text"] for a, b in pairs)


def test_a_table_that_fits_is_kept_whole_with_its_caption(index):
    table = next(
        c
        for c in _chunks(index, filing_id="AAPL_10-K_2024-09-28", section="MD&A")
        if "Total net sales | $ | 391,035" in c["text"] and "Greater China" in c["text"]
    )

    assert table["kind"] == "table"
    assert "net sales by reportable segment" in table["text"]
    assert "| 2024 |  | Change |  | 2023" in table["text"]
    assert "Rest of Asia Pacific" in table["text"]


def test_a_long_table_is_split_into_row_groups_that_repeat_its_header(index):
    tables = [c for c in _chunks(index, ticker="JPM") if c["kind"] == "table"]
    runs = [
        (a, b)
        for a, b in zip(tables, tables[1:], strict=False)
        if a["filing_id"] == b["filing_id"] and b["ordinal"] == a["ordinal"] + 1
    ]
    repeated = [(a, b) for a, b in runs if a["text"].split("\n")[:2] == b["text"].split("\n")[:2]]

    assert repeated
    assert all(a["text"] != b["text"] for a, b in repeated)


def test_a_10q_risk_factors_pointer_is_tagged_as_a_pointer(index):
    chunks = _chunks(index, filing_id="AAPL_10-Q_2025-12-27", section="Risk Factors")

    assert [c["kind"] for c in chunks] == ["risk_pointer"]
    assert "no material changes" in chunks[0]["text"]


# --- Preparing an Answer Context ---------------------------------------------------------


def test_the_brief_example_resolves_its_three_companies(index):
    context = _ask(index, BRIEF_QUESTION)

    assert [c.ticker for c in context.query_scope.companies] == ["AAPL", "TSLA", "JPM"]
    assert [c.coverage for c in context.query_scope.companies] == [
        "tracked",
        "tracked",
        "snapshot",
    ]


def test_sources_come_only_from_the_named_companies_and_cover_each_one(index):
    context = _ask(index, BRIEF_QUESTION)

    assert {s.ticker for s in context.sources} == {"AAPL", "TSLA", "JPM"}
    assert any(s.section == "Risk Factors" for s in context.sources if s.ticker == "JPM")


def test_sources_are_numbered_one_per_filing_and_section(index):
    context = _ask(index, BRIEF_QUESTION)

    assert [s.tag for s in context.sources] == [f"S{i}" for i in range(1, len(context.sources) + 1)]
    pairs = [(s.filing_id, s.section) for s in context.sources]
    assert len(pairs) == len(set(pairs))
    tickers = [s.ticker for s in context.sources]
    assert tickers == sorted(tickers, key=["AAPL", "TSLA", "JPM"].index)  # grouped by Company


def test_sources_fit_the_context_budget(index):
    context = _ask(index, BRIEF_QUESTION)

    per_company = {}
    for source in context.sources:
        per_company[source.ticker] = per_company.get(source.ticker, 0) + count_tokens(source.text)
    assert sum(per_company.values()) <= CONTEXT_BUDGET_TOKENS * 1.05
    assert all(t <= CONTEXT_BUDGET_TOKENS / 3 * 1.05 for t in per_company.values())


def test_the_context_budget_can_be_set_per_call(index):
    messages = [Message("user", BRIEF_QUESTION)]

    small = prepare_answer_context(messages, index, context_budget=9_000)
    default = prepare_answer_context(messages, index)

    per_company = {}
    for source in small.sources:
        per_company[source.ticker] = per_company.get(source.ticker, 0) + count_tokens(source.text)
    assert set(per_company) == {"AAPL", "TSLA", "JPM"}
    assert all(t <= 3_000 * 1.05 for t in per_company.values())
    assert sum(count_tokens(s.text) for s in default.sources) > 2 * sum(per_company.values())


def test_a_risk_pointer_is_cited_as_it_stands_but_never_ranked(index):
    pointer = _chunks(index, filing_id="AAPL_10-Q_2025-12-27", section="Risk Factors")[0]

    risk = _ask(index, "What are Apple's risk factors?")
    other = _ask(index, "Did Apple report material changes in its 10-Q for the latest quarter?")

    cited = [s for s in risk.sources if s.filing_id == "AAPL_10-Q_2025-12-27"]
    assert [(s.section, s.text) for s in cited] == [("Risk Factors", pointer["text"])]
    assert risk.sources[0].filing_id == "AAPL_10-K_2025-09-27"  # the risks come first
    assert other.sources
    assert not any(pointer["text"] in s.text for s in other.sources)


def test_a_source_carries_its_citation_metadata_and_passage(index):
    context = _ask(index, "What does Tesla say about Gigafactory Texas?")

    source = context.sources[0]
    assert source.ticker == "TSLA"
    assert source.company == "Tesla Inc"
    assert source.form_type in {"10-K", "10-Q"}
    assert source.filing_id == f"TSLA_{source.form_type}_{source.report_period}"
    assert source.fiscal_period
    assert "Texas" in source.text
    assert source.label.startswith(
        f"TSLA {source.form_type} {source.fiscal_period} ({source.calendar_months}), "
    )


def test_the_prompt_renders_rules_sources_and_question(index):
    context = _ask(index, BRIEF_QUESTION)

    assert context.prompt_version == PROMPT_VERSION == "v18"
    system, user = context.messages
    assert system.role == "system"
    assert "[S3]" in system.content and "general knowledge" in system.content
    assert user.role == "user"
    for source in context.sources:
        assert f"[{source.tag}] {source.label}" in user.content
    assert "## Apple Inc (AAPL)" in user.content
    assert user.content.rstrip().endswith(BRIEF_QUESTION)


@pytest.mark.parametrize(
    ("question", "tickers"),
    [
        ("How does TSLA describe competition compared with Apple Inc?", ["TSLA", "AAPL"]),
        ("What does JPMorgan Chase say about credit risk?", ["JPM"]),
        ("What does J.P. Morgan say about credit risk?", ["JPM"]),
        ("Did Target miss its sales target?", ["TGT"]),
        ("Which retailer missed its sales target?", []),
        ("What are the risks of an apple orchard?", []),
    ],
)
def test_companies_are_recognised_by_ticker_and_name(index, question, tickers):
    context = _ask(index, question)

    assert [c.ticker for c in context.query_scope.companies] == tickers


def test_a_question_naming_no_company_searches_every_company(index):
    context = _ask(index, "Which companies discuss Gigafactory production?")

    assert context.query_scope.companies == ()
    assert any(s.ticker == "TSLA" for s in context.sources)


def test_fts5_syntax_in_a_question_is_searched_as_words(index):
    question = 'Apple "supply chain" NOT tariffs* OR NEAR(China) text:iPhone ^risk - AND (('

    context = _ask(index, question)

    assert [c.ticker for c in context.query_scope.companies] == ["AAPL"]
    assert context.sources


def test_earlier_turns_are_rendered_as_context_without_their_source_tags(index):
    conversation = [
        Message("user", BRIEF_QUESTION),
        Message("assistant", "Apple depends on global supply chains [S1][S2]."),
        Message("user", "Which of them is most exposed to China?"),
    ]

    context = prepare_answer_context(conversation, index)

    user = context.messages[1].content
    assert "Earlier conversation" in user
    assert "User: " + BRIEF_QUESTION in user
    assert "Assistant: Apple depends on global supply chains." in user
    assert "[S1][S2]" not in user
    assert user.rstrip().endswith("Which of them is most exposed to China?")


def test_the_conversation_must_end_with_a_user_message(index):
    with pytest.raises(ValueError):
        prepare_answer_context([Message("user", "Apple?"), Message("assistant", "Yes.")], index)
    with pytest.raises(ValueError):
        prepare_answer_context([Message("user", "   ")], index)
    with pytest.raises(ValueError):
        prepare_answer_context([], index)


def test_a_missing_index_says_how_to_build_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="make index"):
        _ask(tmp_path / "missing.sqlite", BRIEF_QUESTION)


# --- Time windows ------------------------------------------------------------------------


def _scope_filings(context, ticker):
    return [f.filing_id for f in context.query_scope.filings if f.ticker == ticker]


def test_the_last_two_years_is_eight_quarters_up_to_the_companys_latest_filing(index):
    context = _ask(index, "How has NVIDIA's revenue changed over the last two years?")

    assert context.query_scope.time_window.label == "last 2 years"
    assert _scope_filings(context, "NVDA") == [
        "NVDA_10-K_2024-01-28",
        "NVDA_10-Q_2024-04-28",
        "NVDA_10-Q_2024-07-28",
        "NVDA_10-Q_2024-10-27",
        "NVDA_10-K_2025-01-26",
        "NVDA_10-Q_2025-04-27",
        "NVDA_10-Q_2025-07-27",
        "NVDA_10-Q_2025-10-26",
    ]
    # Text is retrieved only from the window. (A Facts Source may come from earlier: the
    # 10-Qs a derived fourth quarter subtracts.)
    text = [s for s in context.sources if s.kind == "text"]
    assert text
    assert {s.filing_id for s in text} <= set(_scope_filings(context, "NVDA"))


def test_each_company_anchors_its_window_on_its_own_latest_filing(index):
    context = _ask(index, "How did Apple and Tesla describe demand over the past three years?")

    apple, tesla = _scope_filings(context, "AAPL"), _scope_filings(context, "TSLA")
    assert len(apple) == len(tesla) == 12
    assert (apple[0], apple[-1]) == ("AAPL_10-Q_2023-04-01", "AAPL_10-Q_2025-12-27")
    assert (tesla[0], tesla[-1]) == ("TSLA_10-Q_2023-03-31", "TSLA_10-K_2025-12-31")


@pytest.mark.parametrize(
    ("phrase", "label"),
    [
        ("in the last year", "last 1 year"),
        ("over the past 3 years", "last 3 years"),
        ("in the previous two quarters", "last 2 quarters"),
    ],
)
def test_time_phrases_are_read_with_their_count_and_unit(index, phrase, label):
    context = _ask(index, f"How did Tesla's deliveries change {phrase}?")

    assert context.query_scope.time_window.label == label


def test_latest_is_the_latest_10k_plus_any_later_10qs(index):
    context = _ask(
        index, "What do Apple, Tesla and NVIDIA say about pricing in their latest Filings?"
    )

    assert context.query_scope.time_window.label == "latest"
    assert _scope_filings(context, "AAPL") == ["AAPL_10-K_2025-09-27", "AAPL_10-Q_2025-12-27"]
    assert _scope_filings(context, "TSLA") == ["TSLA_10-K_2025-12-31"]
    assert _scope_filings(context, "NVDA") == [
        "NVDA_10-K_2025-01-26",
        "NVDA_10-Q_2025-04-27",
        "NVDA_10-Q_2025-07-27",
        "NVDA_10-Q_2025-10-26",
    ]
    assert {s.filing_id for s in context.sources} <= {
        f.filing_id for f in context.query_scope.filings
    }


def test_a_question_with_no_time_phrase_searches_every_filing(index):
    context = _ask(index, "What does Tesla say about Gigafactory Texas?")

    assert context.query_scope.time_window.label == "all Filings"
    assert len(_scope_filings(context, "TSLA")) == 16


def test_a_scope_filing_carries_its_periods(index):
    context = _ask(index, "What did Apple say in its most recent Filings about tariffs?")

    latest = context.query_scope.filings[-1]
    assert (latest.filing_id, latest.form_type, latest.report_period, latest.fiscal_period) == (
        "AAPL_10-Q_2025-12-27",
        "10-Q",
        "2025-12-27",
        "Q1 FY2026",
    )


# --- Section hints -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "section"),
    [
        ("What are the main risk factors in Apple's latest Filings?", "Risk Factors"),
        ("What does Tesla's latest MD&A say about deliveries?", "MD&A"),
        ("What does Apple's latest management's discussion say about services?", "MD&A"),
        ("What interest rate risk does Tesla report in its latest Filings?", "Market Risk"),
        ("Summarise the business overview in Target's latest Filings.", "Business"),
    ],
)
def test_a_section_hint_prefers_that_section(index, question, section):
    context = _ask(index, question)

    assert context.query_scope.sections == (section,)
    assert context.sources
    assert {s.section for s in context.sources} == {section}


def test_market_risk_phrases_are_not_read_as_risk_factors(index):
    context = _ask(index, "What foreign currency and interest rate risks does Apple disclose?")

    assert context.query_scope.sections == ("Market Risk",)


@pytest.mark.parametrize(
    "question",
    [
        # One "risk" closing a list of risk kinds.
        "How do Apple's and Tesla's interest rate and foreign exchange risk compare?",
        "What interest rate, currency and commodity price risks does Tesla report?",
        "What currency risk does Apple disclose?",
        "What FX risk does Apple report?",
        "What foreign exchange risk does Apple disclose?",
        "What exchange risk does Apple face?",
        "What foreign exchange exposure does Apple report?",
        "How large is Apple's interest rate exposure?",
        "What interest rate sensitivity does Apple disclose?",
        "What commodity price risk does Tesla disclose?",
    ],
)
def test_market_risk_phrasings_search_market_risk_not_risk_factors(index, question):
    context = _ask(index, question)

    assert context.query_scope.sections == ("Market Risk",)
    assert "Market Risk" in {p.section for p in context.query_scope.searched}
    # A 10-Q whose Item 3 is a stub ("no material changes") is searched whole, so other
    # Sections may join; the hint still plans Market Risk, never Risk Factors alone.
    assert "Market Risk" in {s.section for s in context.sources}


CYBER_SECTIONS = ("Cybersecurity", "Risk Factors", "MD&A")


@pytest.mark.parametrize(
    "question",
    [
        "What cybersecurity risks does Tesla describe?",
        "How does Apple describe cyber threats to its systems?",
        "What does Apple say about a data breach?",
        "How does Tesla guard against a cyberattack?",
        "How does Apple manage information security?",
    ],
)
def test_a_cybersecurity_question_searches_cybersecurity_risk_factors_and_mdna(index, question):
    context = _ask(index, question)

    assert context.query_scope.sections == CYBER_SECTIONS
    assert context.query_scope.time_window.label == "latest"
    assert context.sources
    assert {s.section for s in context.sources} <= set(CYBER_SECTIONS)
    assert {s.filing_id for s in context.sources if s.kind == "text"} <= {
        f.filing_id for f in context.query_scope.filings
    }


def test_a_cybersecurity_question_finds_the_cybersecurity_section_of_the_latest_10k(index):
    context = _ask(index, "What cybersecurity risks does Tesla describe?")

    assert _scope_filings(context, "TSLA") == ["TSLA_10-K_2025-12-31"]
    assert ("TSLA_10-K_2025-12-31", "Cybersecurity") in {
        (s.filing_id, s.section) for s in context.sources
    }
    assert {p.section for p in context.query_scope.searched} == set(CYBER_SECTIONS)


def test_a_cybersecurity_question_with_a_time_phrase_keeps_its_window(index):
    context = _ask(
        index, "How has Tesla's cybersecurity disclosure changed over the last two years?"
    )

    assert context.query_scope.time_window.label == "last 2 years"
    assert {s.section for s in context.sources} <= set(CYBER_SECTIONS)


@pytest.mark.parametrize(
    "question",
    [
        "What are Apple's and Tesla's regulatory risks, and how are they addressing them?",
        "What risks does Apple face, and how is it managing them?",
        "What risks does Tesla disclose, and how does it mitigate them?",
        "What supply risks does Apple face, and what is it doing in response?",
        "What risks does Tesla face, and how is it handling them?",
    ],
)
def test_a_risk_question_asking_how_they_respond_also_searches_business_and_mdna(index, question):
    context = _ask(index, question)

    assert set(context.query_scope.sections) == {"Risk Factors", "Business", "MD&A"}
    assert context.query_scope.time_window.label == "latest"
    sections = {s.section for s in context.sources}
    assert "Risk Factors" in sections
    assert sections & {"Business", "MD&A"}
    assert {s.filing_id for s in context.sources} <= {
        f.filing_id for f in context.query_scope.filings
    }


def test_a_risk_question_asking_how_they_respond_still_cites_10q_risk_pointers(index):
    context = _ask(
        index, "What are Apple's and Tesla's regulatory risks, and how are they addressing them?"
    )

    pairs = {(s.filing_id, s.section) for s in context.sources}
    # Apple's Q1 FY2026 10-Q points back to the 10-K: cited as it stands, never searched.
    assert ("AAPL_10-Q_2025-12-27", "Risk Factors") in pairs
    searched = {(p.filing_id, p.section) for p in context.query_scope.searched}
    assert ("AAPL_10-Q_2025-12-27", "Risk Factors") not in searched
    assert ("AAPL_10-K_2025-09-27", "Risk Factors") in searched
    assert ("AAPL_10-K_2025-09-27", "Business") in searched


def test_a_response_phrase_without_a_risk_hint_adds_no_section(index):
    context = _ask(index, "How is Apple managing its services business?")

    assert context.query_scope.sections == ()


@pytest.mark.parametrize(
    "question",
    [
        "How dependent is Apple on its largest customers?",
        "How dependent is Tesla on its suppliers?",
        "What is NVIDIA's customer concentration?",
        "How much does Apple rely on outside manufacturers?",
        "Does Tesla have sole source suppliers?",
        "How much revenue does Target get from government contracts?",
    ],
)
def test_a_dependence_question_searches_business_and_risk_factors_of_the_latest_filings(
    index, question
):
    context = _ask(index, question)

    assert set(context.query_scope.sections) == {"Business", "Risk Factors"}
    assert context.query_scope.time_window.label == "latest"
    assert "Business" in {p.section for p in context.query_scope.searched}
    assert context.sources
    # A 10-Q has no Business Section and its Risk Factors point back to the 10-K or are
    # searched as Risk Factors: it is never searched whole.
    assert {s.section for s in context.sources} <= {"Business", "Risk Factors"}


def test_a_dependence_question_cites_the_business_section_of_the_latest_10k(index):
    context = _ask(index, "How dependent is Apple on its suppliers?")

    assert ("AAPL_10-K_2025-09-27", "Business") in {
        (s.filing_id, s.section) for s in context.sources
    }


def test_a_dependence_question_with_a_time_phrase_keeps_its_window(index):
    context = _ask(
        index, "How has Apple's dependence on its suppliers changed over the last two years?"
    )

    assert context.query_scope.time_window.label == "last 2 years"
    assert "Business" in context.query_scope.sections
    searched = {(p.filing_id, p.section) for p in context.query_scope.searched}
    assert {("AAPL_10-K_2024-09-28", "Business"), ("AAPL_10-K_2025-09-27", "Business")} <= searched


def test_a_dependence_phrase_beside_another_hint_adds_business_to_it(index):
    context = _ask(index, "What does Tesla's MD&A say about its reliance on suppliers?")

    assert set(context.query_scope.sections) == {"MD&A", "Business"}
    assert context.query_scope.time_window.label == "latest"


def test_a_follow_up_inherits_the_sections_a_dependence_phrase_planned(index):
    context = prepare_answer_context(
        [
            Message("user", "How dependent is Apple on its suppliers?"),
            Message("assistant", "Apple depends on outsourcing partners [S1]."),
            Message("user", "And Tesla?"),
        ],
        index,
    )

    assert [c.ticker for c in context.query_scope.companies] == ["TSLA"]
    assert set(context.query_scope.sections) == {"Business", "Risk Factors"}
    assert context.query_scope.time_window.label == "latest"


LEGAL_PROCEEDINGS = ("Legal Proceedings", "Financial Statements")


def _section_tokens(index, filing_id, section):
    return sum(c["tokens"] for c in _chunks(index, filing_id=filing_id, section=section))


def test_a_legal_proceedings_question_also_searches_the_financial_statements(index):
    context = _ask(index, "What legal proceedings does Apple disclose in its latest Filings?")

    assert context.query_scope.sections == LEGAL_PROCEEDINGS
    assert _searched(context) == [
        ("AAPL", "AAPL_10-K_2025-09-27", "Legal Proceedings"),
        ("AAPL", "AAPL_10-K_2025-09-27", "Financial Statements"),
        ("AAPL", "AAPL_10-Q_2025-12-27", "Legal Proceedings"),
        ("AAPL", "AAPL_10-Q_2025-12-27", "Financial Statements"),
    ]
    sections = {s.section for s in context.sources}
    assert "Legal Proceedings" in sections  # Apple's Item 3 states its cases
    assert sections <= set(LEGAL_PROCEEDINGS)


def test_a_stub_legal_proceedings_is_answered_from_the_financial_statements(index):
    # Tesla's Item 3 only points to the contingencies note: "see Note 15".
    assert _section_tokens(index, "TSLA_10-K_2025-12-31", "Legal Proceedings") < STUB_TOKENS

    context = _ask(index, "What legal proceedings does Tesla disclose in its latest Filings?")

    assert context.query_scope.sections == LEGAL_PROCEEDINGS
    assert _searched(context) == [("TSLA", "TSLA_10-K_2025-12-31", "Financial Statements")]
    assert context.sources
    assert {(s.filing_id, s.section) for s in context.sources} == {
        ("TSLA_10-K_2025-12-31", "Financial Statements")
    }
    assert any(re.search(r"legal proceedings", s.text, re.I) for s in context.sources)


def test_a_stub_section_falls_back_to_the_whole_filing(index):
    # JPMorgan's Item 3 and Item 8 both point to pages of its annual report.
    for section in LEGAL_PROCEEDINGS:
        assert _section_tokens(index, "JPM_10-K_2025-12-31", section) < STUB_TOKENS

    context = _ask(index, "What legal proceedings does JPMorgan disclose in its latest Filings?")

    assert context.query_scope.sections == LEGAL_PROCEEDINGS
    assert {s.filing_id for s in context.sources} == {"JPM_10-K_2025-12-31"}
    assert {s.section for s in context.sources} - set(LEGAL_PROCEEDINGS)


def test_a_missing_section_falls_back_to_the_whole_filing(index):
    assert not _chunks(index, filing_id="JPM_10-Q_2025-09-30", section="MD&A")

    context = _ask(
        index, "What does JPMorgan's MD&A say about net interest income in the last two quarters?"
    )

    assert _scope_filings(context, "JPM") == ["JPM_10-Q_2025-09-30", "JPM_10-K_2025-12-31"]
    assert "JPM_10-Q_2025-09-30" in {s.filing_id for s in context.sources}
    assert {s.section for s in context.sources} - {"MD&A"}


# --- Search terms ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "topic"),
    [
        # A Risk Factors Section's chunks nearly all say "risk", and many say "key" or
        # "main", so those words would rank passages that never mention the topic.
        ("What are Tesla's key competition risks?", "competi"),
        ("What are Target's key competition risks?", "competi"),
    ],
)
def test_on_the_risk_route_the_topic_word_outranks_risk_and_generic_words(index, question, topic):
    # The ranker given the shipped ranking keeps it, and shows it to the test.
    ranker = _Recorder()
    context = prepare_answer_context(
        [Message("user", question)], index, ranker=ranker, context_budget=2000
    )

    assert context.query_scope.sections == ("Risk Factors",)
    in_scope = {f.filing_id for f in context.query_scope.filings}
    text = {c["id"]: c["text"] for c in _chunks(index, section="Risk Factors")}
    on_topic = {
        c["id"]
        for c in _chunks(index, section="Risk Factors")
        if c["filing_id"] in in_scope and topic in c["text"].lower()
    }
    (request,) = ranker.requests
    # The passages retrieved, best first: the ones on the topic rank before any other,
    # which only fill what is left of the budget once a larger one on the topic doesn't.
    # A retrieved chunk's whole text is in its Source, joined to any next to it.
    retrieved = [
        topic in text[i].lower()
        for i in request.lexical
        if any(text[i] in s.text for s in context.sources)
    ]
    assert 0 < sum(retrieved) < len(on_topic)  # more passages on the topic than fit
    assert retrieved == sorted(retrieved, reverse=True)


@pytest.mark.parametrize(
    "question",
    [
        "What are Apple's main risks?",
        "What are the key risk factors for Tesla?",
        "What is Apple's biggest litigation?",
        "What are NVIDIA's most important risks?",
    ],
)
def test_a_question_of_only_generic_and_hint_words_still_gets_sources(index, question):
    context = _ask(index, question)

    assert context.query_scope.sections
    assert _passages(context)


# --- The topic table ---------------------------------------------------------------------


def _without_topic_table(monkeypatch, ask):
    with monkeypatch.context() as patch:
        patch.setattr(_topics, "TOPICS", ())
        return ask()


def test_a_topic_phrases_terms_bring_in_a_passage_the_questions_own_words_miss(
    sector_index, monkeypatch
):
    # Pfizer states its regulatory risk as the IRA's Medicare price negotiation and
    # government price controls, often without the word "regulatory".
    question = "What regulatory risks does Pfizer face?"
    added = _topics.added_terms(question, "Health Care")
    names_one = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in added) + r")\b", re.I)

    def worded_as_the_filing(context):
        return [
            p
            for _, p in _passages(context)
            if names_one.search(p) and not re.search(r"\bregulatory\b", p, re.I)
        ]

    def ask():
        return prepare_answer_context(
            [Message("user", question)], sector_index, context_budget=4000
        )

    assert worded_as_the_filing(ask())
    assert not worded_as_the_filing(_without_topic_table(monkeypatch, ask))


@pytest.mark.parametrize(
    "question",
    [
        BRIEF_QUESTION,
        "How has NVIDIA's revenue changed over the last two years?",
        "What legal proceedings is Apple involved in?",
        "What are Tesla's main risks?",
        # A topic held to health care Companies leaves the others' search as it was.
        "What regulatory risks does JPMorgan face?",
    ],
)
def test_a_question_with_no_topic_phrase_for_its_companies_searches_exactly_as_before(
    index, monkeypatch, question
):
    context = _ask(index, question)
    before = _without_topic_table(monkeypatch, lambda: _ask(index, question))

    assert context.sources == before.sources
    assert context.messages == before.messages


# --- The outlook route -------------------------------------------------------------------

APPLE_LATEST = ["AAPL_10-K_2025-09-27", "AAPL_10-Q_2025-12-27"]


@pytest.mark.parametrize(
    "question",
    [
        "What is Apple's outlook for its Services business?",
        "What does Apple expect for its gross margin?",
        "What does Apple say it expects from tariffs?",
        "What are Apple's expectations for its Services revenue?",
        "What guidance does Apple give for its gross margin?",
        "What does Apple forecast for its Services business?",
        "How does Apple see its gross margin going forward?",
        "What does Apple say about its gross margin next year?",
    ],
)
def test_an_outlook_question_searches_only_the_latest_mdna(index, question):
    context = _ask(index, question)

    assert context.query_scope.sections == ("MD&A",)
    assert context.query_scope.time_window.label == "latest"
    assert _scope_filings(context, "AAPL") == APPLE_LATEST
    assert context.sources
    text = [s for s in context.sources if s.kind == "text"]
    assert {s.section for s in text} == {"MD&A"}
    assert {s.filing_id for s in text} <= set(APPLE_LATEST)


def test_an_outlook_question_over_the_last_two_years_keeps_that_window(index):
    context = _ask(index, "How has NVIDIA's growth outlook changed over the last two years?")

    assert context.query_scope.sections == ("MD&A",)
    assert context.query_scope.time_window.label == "last 2 years"
    assert len(_scope_filings(context, "NVDA")) == 8
    assert {s.section for s in context.sources if s.kind == "text"} == {"MD&A"}


def test_an_outlook_for_a_year_after_the_latest_filing_reads_the_latest_mdna(index):
    # Tesla's latest Filing is its FY2025 10-K, so 2026 names no Filing of Tesla's.
    for question in ("What is Tesla's outlook for 2026?", "What does Tesla plan for 2026?"):
        context = _ask(index, question)

        assert context.query_scope.sections == ("MD&A",), question
        assert context.query_scope.time_window.label == "latest", question
        assert _scope_filings(context, "TSLA") == ["TSLA_10-K_2025-12-31"]
        assert {(s.filing_id, s.section) for s in context.sources if s.kind == "text"} == {
            ("TSLA_10-K_2025-12-31", "MD&A")
        }


def test_a_year_a_filing_covers_is_not_an_outlook(index):
    context = _ask(index, "What did Tesla say about deliveries for 2024?")

    assert context.query_scope.sections == ()
    assert context.query_scope.periods == ("FY2024",)
    assert context.query_scope.time_window.label == "all Filings"


def test_an_outlook_question_still_states_that_guidance_is_not_in_the_filings(index):
    context = _ask(index, "What is Tesla's outlook for 2026?")

    assert [(g.kind, g.companies) for g in context.coverage_gaps] == [("no_guidance", ("TSLA",))]


# --- The Overview route and the document-order fill -----------------------------------

OVERVIEW = ("Business", "MD&A", "Risk Factors")


def _text_places(context, ticker):
    return {
        (s.filing_id, s.section) for s in context.sources if s.kind == "text" and s.ticker == ticker
    }


def _opening_chunk(index, filing_id, section):
    rows = [
        c
        for c in _chunks(index, filing_id=filing_id, section=section)
        if c["kind"] != "risk_pointer"
    ]
    return min(rows, key=lambda c: c["ordinal"])


def _source_tokens(context):
    return sum(count_tokens(s.text) for s in context.sources)


def test_a_question_with_no_topic_reads_each_companys_latest_business_mdna_and_risk_factors(
    overview_index,
):
    context = _ask(overview_index, "Compare Coke and Pepsi")

    scope = context.query_scope
    assert [c.ticker for c in scope.companies] == ["KO", "PEP"]
    assert scope.sections == OVERVIEW
    assert scope.time_window.label == "latest"
    # Coca-Cola's latest Business and Risk Factors are in its FY2024 10-K; its latest MD&A
    # is in its Q3 FY2025 10-Q, whose Risk Factors only point back to the 10-K.
    planned = [
        ("KO", "KO_10-K_2024-12-31", "Business"),
        ("KO", "KO_10-K_2024-12-31", "Risk Factors"),
        ("KO", "KO_10-Q_2025-09-26", "MD&A"),
        ("PEP", "PEP_10-K_2025-12-27", "Business"),
        ("PEP", "PEP_10-K_2025-12-27", "MD&A"),
        ("PEP", "PEP_10-K_2025-12-27", "Risk Factors"),
    ]
    assert _searched(context) == planned
    for _, filing_id, section in planned:
        (source,) = [s for s in context.sources if (s.filing_id, s.section) == (filing_id, section)]
        # Opening chunks first: each Section's Source starts where the Section does.
        assert source.text.startswith(_opening_chunk(overview_index, filing_id, section)["text"])
    assert {s.section for s in context.sources if s.ticker == "KO"} == set(OVERVIEW)
    assert {s.section for s in context.sources if s.ticker == "PEP"} == set(OVERVIEW)
    assert CONTEXT_BUDGET_TOKENS * 0.8 <= _source_tokens(context) <= CONTEXT_BUDGET_TOKENS


def test_a_broad_question_about_jpmorgan_reads_its_latest_10k(index):
    context = _ask(index, "How is JP Morgan doing?")

    assert [c.ticker for c in context.query_scope.companies] == ["JPM"]
    assert context.query_scope.sections == OVERVIEW
    # JPMorgan's Item 7 is a pointer to the annual report's financial review (a stub),
    # so its latest 10-K is read in Business and Risk Factors.
    assert _searched(context) == [
        ("JPM", "JPM_10-K_2025-12-31", "Business"),
        ("JPM", "JPM_10-K_2025-12-31", "Risk Factors"),
    ]
    assert _text_places(context, "JPM") == {
        ("JPM_10-K_2025-12-31", "Business"),
        ("JPM_10-K_2025-12-31", "Risk Factors"),
    }
    for source in context.sources:
        assert source.text.startswith(
            _opening_chunk(index, source.filing_id, source.section)["text"]
        )
    assert CONTEXT_BUDGET_TOKENS * 0.8 <= _source_tokens(context) <= CONTEXT_BUDGET_TOKENS


def test_a_question_naming_only_a_company_takes_the_overview_route(index):
    context = _ask(index, "What about Apple?")

    assert context.query_scope.sections == OVERVIEW
    # The Q1 FY2026 10-Q's Risk Factors only point back to the 10-K: cited as they stand.
    assert _text_places(context, "AAPL") == {
        ("AAPL_10-K_2025-09-27", "Business"),
        ("AAPL_10-K_2025-09-27", "Risk Factors"),
        ("AAPL_10-Q_2025-12-27", "MD&A"),
        ("AAPL_10-Q_2025-12-27", "Risk Factors"),
    }
    assert "No Sources were found" not in context.messages[1].content


def test_a_follow_up_switching_company_after_an_overview_takes_it_too(index):
    conversation = [
        Message("user", "How is JP Morgan doing?"),
        Message("assistant", "JPMorgan is the largest US bank [S1]."),
        Message("user", "And what about Tesla?"),
    ]

    context = prepare_answer_context(conversation, index)

    assert [c.ticker for c in context.query_scope.companies] == ["TSLA"]
    assert context.query_scope.sections == OVERVIEW
    assert {s.section for s in context.sources} == set(OVERVIEW)


@pytest.mark.parametrize(
    "question",
    [
        "What does Apple say about tariffs?",
        "How has Apple changed?",
        "How was Apple doing over the last two years?",
        "How was Apple doing in fiscal 2024?",
        "What are Apple's main risks?",
    ],
)
def test_a_topic_a_change_a_time_phrase_or_a_hint_keeps_its_own_route(index, question):
    assert _ask(index, question).query_scope.sections != OVERVIEW


TESLA_OUTLOOK_2026 = "What is Tesla's outlook for 2026?"


def test_a_plan_whose_matches_fall_short_fills_its_budget_in_document_order(index):
    mdna = _mdna(index)
    first, fourth = sorted(mdna)[:3], mdna[sorted(mdna)[3]]
    matched = mdna[max(mdna)]
    budget = matched["tokens"] + sum(mdna[o]["tokens"] for o in first)

    source = _retrieve(index, [matched], context_budget=budget)

    # The one matched chunk, the MD&A's last, leaves the budget unspent: the MD&A's
    # opening chunks fill it, and the fourth no longer fits.
    assert source.text.startswith(mdna[first[0]]["text"])
    assert source.text.endswith(GAP + matched["text"])
    assert source.text.count(GAP) == 1
    assert _middle(fourth) not in source.text
    # Filled up to the budget and no further.
    assert _read(mdna, source.text) == {*first, max(mdna)}
    assert sum(mdna[o]["tokens"] for o in _read(mdna, source.text)) == budget


def test_a_one_company_outlook_reads_the_whole_mdna_when_it_fits(index):
    context = _ask(index, TESLA_OUTLOOK_2026)

    (source,) = [s for s in context.sources if s.kind == "text"]
    assert (source.filing_id, source.section) == (TESLA_10K, "MD&A")
    # The MD&A (about 15,500 tokens) fits in the budget, so every chunk of it is read.
    assert GAP not in source.text
    assert all(c["text"][-100:] in source.text for c in _mdna(index).values())
    assert _source_tokens(context) <= CONTEXT_BUDGET_TOKENS


def test_a_plan_whose_matches_fill_the_budget_is_not_filled(index):
    mdna = _mdna(index)
    ranked = [mdna[o] for o in sorted(mdna, reverse=True)][:6]
    # The best five fill the budget but for one token less than the sixth needs: the sixth
    # does not fit, so the plan's matches have not run out, and nothing is added, though
    # the MD&A's shorter unmatched chunks would fit in what is left.
    budget = sum(c["tokens"] for c in ranked) - 1
    assert min(c["tokens"] for o, c in mdna.items() if c not in ranked) < ranked[5]["tokens"]

    context = _retrieve_context(index, ranked, context_budget=budget)
    source = _mdna_source(context)

    assert source.text.startswith(ranked[4]["text"])
    assert ranked[5]["text"][:100] not in source.text
    assert mdna[sorted(mdna)[0]]["text"] not in source.text
    # Exactly the five ranked chunks, as before the fill: no other MD&A chunk reaches the
    # Sources or the prompt.
    chosen = {c["ordinal"] for c in ranked[:5]}
    assert _read(mdna, source.text) == chosen
    prompt = "\n".join(m.content for m in context.messages)
    assert _read(mdna, prompt) == chosen


# --- Open questions ------------------------------------------------------------------------


def _latest_filings(indexed_filings):
    by_ticker = {}
    for f in sorted(indexed_filings, key=lambda f: f.report_period):
        by_ticker.setdefault(f.ticker, []).append(f)
    latest = set()
    for own in by_ticker.values():
        annual = [i for i, f in enumerate(own) if f.form_type == "10-K"]
        latest |= {f.filing_id for f in own[annual[-1] :]}
    return latest


def test_a_question_naming_no_company_and_no_time_phrase_reads_the_latest_filings(
    index, indexed_filings
):
    context = _ask(index, "Which companies discuss Gigafactory production?")

    assert context.query_scope.time_window.label == "latest"
    assert {p.filing_id for p in context.query_scope.searched} == _latest_filings(indexed_filings)
    assert any(s.ticker == "TSLA" for s in context.sources)
    assert {s.filing_id for s in context.sources} <= _latest_filings(indexed_filings)


@pytest.mark.parametrize(
    ("question", "label"),
    [
        ("How has Gigafactory production changed?", "all Filings"),
        (
            "Which companies discussed Gigafactory production over the last two years?",
            "last 2 years",
        ),
        ("Which companies discussed Gigafactory production in fiscal 2023?", "all Filings"),
    ],
)
def test_an_open_change_question_or_named_period_keeps_its_window(index, question, label):
    assert _ask(index, question).query_scope.time_window.label == label


# --- The places searched -----------------------------------------------------------------


def _searched(context):
    return [(p.ticker, p.filing_id, p.section) for p in context.query_scope.searched]


def test_a_hinted_question_records_the_hinted_section_of_each_filing_searched(index):
    context = _ask(index, "What does Tesla's latest MD&A say about deliveries?")

    assert _searched(context) == [("TSLA", "TSLA_10-K_2025-12-31", "MD&A")]


def test_a_risk_question_records_each_risk_factors_searched_and_not_the_pointer(index):
    context = _ask(index, BRIEF_QUESTION)

    # Apple's Q1 FY2026 10-Q points back to the 10-K: it is cited as it stands, not
    # searched.
    assert _searched(context) == [
        ("AAPL", "AAPL_10-K_2025-09-27", "Risk Factors"),
        ("TSLA", "TSLA_10-K_2025-12-31", "Risk Factors"),
        ("JPM", "JPM_10-K_2025-12-31", "Risk Factors"),
    ]
    assert ("AAPL_10-Q_2025-12-27", "Risk Factors") in {
        (s.filing_id, s.section) for s in context.sources
    }


def test_a_filing_searched_whole_is_recorded_with_no_section(index):
    stub = _ask(index, "What legal proceedings does JPMorgan disclose in its latest Filings?")
    unhinted = _ask(index, "How does Apple describe its services business?")

    assert _searched(stub) == [("JPM", "JPM_10-K_2025-12-31", None)]
    assert _searched(unhinted) == [
        ("AAPL", f.filing_id, None) for f in unhinted.query_scope.filings
    ]
    assert len(_searched(unhinted)) == 16


def test_a_question_naming_no_company_records_every_filing_searched_whole(index, indexed_filings):
    context = _ask(index, "Which companies discuss artificial intelligence?")

    assert {(p.filing_id, p.section) for p in context.query_scope.searched} == {
        (f, None) for f in _latest_filings(indexed_filings)
    }


def test_a_question_about_only_missing_companies_searches_nowhere(index):
    context = _ask(index, "What are Citigroup's main risk factors?")

    assert context.query_scope.searched == ()


# --- Risk routing ------------------------------------------------------------------------


def test_the_brief_risk_comparison_retrieves_each_latest_10k_risk_factors(index):
    context = _ask(index, BRIEF_QUESTION)

    pairs = {(s.filing_id, s.section) for s in context.sources}
    assert {
        ("AAPL_10-K_2025-09-27", "Risk Factors"),
        ("TSLA_10-K_2025-12-31", "Risk Factors"),
        ("JPM_10-K_2025-12-31", "Risk Factors"),
    } <= pairs
    assert pairs <= {
        ("AAPL_10-K_2025-09-27", "Risk Factors"),
        ("AAPL_10-Q_2025-12-27", "Risk Factors"),  # "no material changes", cited as it stands
        ("TSLA_10-K_2025-12-31", "Risk Factors"),
        ("JPM_10-K_2025-12-31", "Risk Factors"),
    }
    assert context.query_scope.time_window.label == "latest"


def test_a_risk_question_adds_later_10qs_that_state_risk_text(index):
    context = _ask(index, "Compare the supply chain risks of Apple and NVIDIA.")

    nvidia = {s.filing_id for s in context.sources if s.ticker == "NVDA"}
    assert "NVDA_10-K_2025-01-26" in nvidia
    assert nvidia & {"NVDA_10-Q_2025-04-27", "NVDA_10-Q_2025-07-27", "NVDA_10-Q_2025-10-26"}
    assert {s.section for s in context.sources} == {"Risk Factors"}


def test_a_risk_question_with_a_time_phrase_keeps_its_window(index):
    context = _ask(index, "How have Tesla's risk factors changed over the last two years?")

    assert context.query_scope.time_window.label == "last 2 years"
    assert len(_scope_filings(context, "TSLA")) == 8
    assert {s.section for s in context.sources} == {"Risk Factors"}
    assert {s.filing_id for s in context.sources} & {"TSLA_10-Q_2025-03-31", "TSLA_10-Q_2025-06-30"}


@pytest.mark.parametrize(
    "question",
    [
        "What risk factors did Tesla state in FY2023?",
        "What cybersecurity risks did Tesla describe in FY2023?",
    ],
)
def test_a_risk_question_naming_a_fiscal_period_is_not_held_to_the_latest_filings(index, question):
    context = _ask(index, question)

    assert context.query_scope.time_window.label == "all Filings"
    assert "TSLA_10-K_2023-12-31" in {s.filing_id for s in context.sources}


def test_each_company_gets_an_even_share_of_the_budget_on_the_risk_route(index):
    context = _ask(index, "Compare the risk factors of Apple, Tesla, JPMorgan and NVIDIA.")

    spent = {}
    for source in context.sources:
        spent[source.ticker] = spent.get(source.ticker, 0) + count_tokens(source.text)
    assert set(spent) == {"AAPL", "TSLA", "JPM", "NVDA"}
    share = CONTEXT_BUDGET_TOKENS / 4
    assert all(share * 0.8 <= t <= share * 1.05 for t in spent.values())


def test_a_company_that_cannot_use_its_share_passes_the_rest_to_the_others(index):
    # Tesla's Market Risk Sections hold under 1,000 tokens of distinct text, far less
    # than half the budget; Apple's Market Risk, and the 10-Qs searched whole where it is
    # a stub, hold far more.
    context = _ask(index, "How do Apple's and Tesla's interest rate risk disclosures compare?")

    spent = {}
    for source in context.sources:
        spent[source.ticker] = spent.get(source.ticker, 0) + count_tokens(source.text)
    assert set(spent) == {"AAPL", "TSLA"}
    share = CONTEXT_BUDGET_TOKENS / 2
    assert spent["TSLA"] < share / 4
    assert spent["AAPL"] > share * 1.5
    assert sum(spent.values()) <= CONTEXT_BUDGET_TOKENS * 1.05


def test_a_candidate_too_large_for_what_is_left_is_skipped_and_a_smaller_one_kept(index):
    chunks = {
        c["id"]: c
        for c in _chunks(index, filing_id="TSLA_10-K_2025-12-31", section="Risk Factors")
        if c["kind"] != "risk_pointer"
    }
    by_size = sorted(chunks.values(), key=lambda c: c["tokens"])
    small, first, second = by_size[0], by_size[-1], by_size[-2]
    assert second["tokens"] > small["tokens"] + 10
    budget = first["tokens"] + small["tokens"] + 10

    context = prepare_answer_context(
        [Message("user", "What are Tesla's risk factors?")],
        index,
        ranker=_Recorder(lambda r: [first["id"], second["id"], small["id"]]),
        context_budget=budget,
    )

    passages = [p for _, p in _passages(context)]
    assert sorted(passages) == sorted([first["text"], small["text"]])


def test_an_index_built_by_an_older_version_says_to_rebuild_it(tmp_path, index):
    old = tmp_path / "old.sqlite"
    old.write_bytes(index.read_bytes())
    db = sqlite3.connect(old)
    db.execute("PRAGMA user_version = 1")
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="make index"):
        _ask(old, BRIEF_QUESTION)


# --- Source text -------------------------------------------------------------------------

GAP = "\n[…]\n"
TESLA_10K = "TSLA_10-K_2025-12-31"
# An outlook question reads the MD&A of Tesla's latest Filing, its FY2025 10-K.
TESLA_OUTLOOK = "What is Tesla's outlook?"


def _mdna(index):
    """Tesla's FY2025 10-K MD&A chunks, by ordinal."""
    return {c["ordinal"]: c for c in _chunks(index, filing_id=TESLA_10K, section="MD&A")}


def _retrieve_context(index, rows, **kwargs):
    """The Answer Context of Tesla's outlook when retrieval ranks exactly these chunks,
    within a budget they fill unless another is given (a budget they leave unspent is
    filled from the rest of the MD&A)."""
    ids = [r["id"] for r in rows]
    kwargs.setdefault("context_budget", sum(r["tokens"] for r in rows))
    return prepare_answer_context(
        [Message("user", TESLA_OUTLOOK)],
        index,
        ranker=lambda request: [i for i in ids if i in request.eligible],
        **kwargs,
    )


def _mdna_source(context):
    (source,) = [s for s in context.sources if s.filing_id == TESLA_10K and s.section == "MD&A"]
    return source


def _retrieve(index, rows, **kwargs):
    """The Source citing Tesla's MD&A when retrieval ranks exactly these chunks."""
    return _mdna_source(_retrieve_context(index, rows, **kwargs))


def _middle(chunk):
    middle = len(chunk["text"]) // 2
    return chunk["text"][middle : middle + 100]


def _read(mdna, text):
    """The ordinals of the MD&A chunks a text holds."""
    return {o for o, c in mdna.items() if _middle(c) in text}


def test_adjacent_chunks_join_as_one_passage_with_their_overlap_shown_once(index):
    mdna = _mdna(index)
    run = [mdna[76], mdna[77], mdna[78]]
    assert all(c["kind"] == "prose" for c in run)
    assert all(b["text"][:80] in a["text"] for a, b in zip(run, run[1:], strict=False))

    source = _retrieve(index, [*run, mdna[80]])

    # Ordinal 79 was not retrieved: exactly one marker, before the last chunk.
    assert source.text.count(GAP) == 1
    joined, after = source.text.split(GAP)
    assert after == mdna[80]["text"]
    assert joined.startswith(run[0]["text"])
    assert joined.endswith(run[-1]["text"][-200:])
    # Each chunk's opening repeats the end of the one before it; it is shown once.
    for chunk in run[1:]:
        assert joined.count(chunk["text"][:80]) == 1
    assert len(joined) < sum(len(c["text"]) for c in run)


def test_a_dropped_overlap_is_the_longest_suffix_the_next_chunk_opens_with(index):
    mdna = _mdna(index)
    a, b = mdna[76], mdna[77]
    overlap = max(k for k in range(1, len(b["text"])) if a["text"].endswith(b["text"][:k]))

    source = _retrieve(index, [a, b])

    assert source.text == a["text"] + b["text"][overlap:]


def test_a_table_and_the_prose_after_it_join_with_no_marker_and_no_text_lost(index):
    mdna = _mdna(index)
    table, prose = mdna[90], mdna[91]
    assert (table["kind"], prose["kind"]) == ("table", "prose")

    source = _retrieve(index, [table, prose])

    assert GAP not in source.text
    assert source.text == table["text"] + "\n" + prose["text"]


def test_chunks_that_skip_an_ordinal_are_separated_by_exactly_one_marker(index):
    mdna = _mdna(index)
    chosen = [mdna[76], mdna[78], mdna[80]]

    source = _retrieve(index, chosen)

    assert source.text == GAP.join(c["text"] for c in chosen)


def test_joining_passages_leaves_chunk_selection_and_the_budget_unchanged(index):
    mdna = _mdna(index)
    chosen = [mdna[76], mdna[77], mdna[78], mdna[80]]
    budget = sum(c["tokens"] for c in chosen)

    # Each chunk still costs its whole size: the overlap shown once frees no budget.
    whole = _retrieve(index, chosen, context_budget=budget)
    short = _retrieve(index, chosen, context_budget=budget - 1)

    assert whole.text.endswith(GAP + mdna[80]["text"])
    assert mdna[80]["text"][-200:] not in short.text
    assert short.text.endswith(mdna[78]["text"][-200:])


def test_a_source_records_where_its_best_ranked_chunk_stands_in_its_text(index):
    """The Generation Miss report asks whether a quote falls in it (`edgar_eval.misses`)."""
    mdna = _mdna(index)

    # Ranked best, the chunk after a skipped ordinal stands after the marker.
    skipped = _retrieve(index, [mdna[80], mdna[76], mdna[77]])
    start, end = skipped.best_chunk
    assert skipped.text[start:end] == mdna[80]["text"]
    assert skipped.text[:start].endswith(GAP)

    # Ranked best, a chunk whose opening repeats the one before it stands for the text
    # it adds; the first chunk in body order stands whole.
    a, b = mdna[76], mdna[77]
    joined = _retrieve(index, [b, a])
    start, end = joined.best_chunk
    assert (start, end) == (len(a["text"]), len(joined.text))
    assert b["text"].endswith(joined.text[start:end])
    assert _retrieve(index, [a, b]).best_chunk == (0, len(a["text"]))


def test_a_facts_source_has_no_best_ranked_chunk(index):
    context = prepare_answer_context(
        [Message("user", "What was Apple's revenue in FY2025?")], index
    )

    facts = [s for s in context.sources if s.kind == "facts"]
    assert facts and all(s.best_chunk is None for s in facts)
    assert all(s.best_chunk is not None for s in context.sources if s.kind == "text")


# --- Deduplication -----------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")


def _shingles(text):
    """8-word shingles, the EDA's measure of repeated text (notebook section 6)."""
    words = _WORD.findall(text.lower())
    return {tuple(words[i : i + 8]) for i in range(len(words) - 7)}


def _passages(context):
    """Each passage retrieved (a run of chunks next to each other in the Filing, or a
    chunk's new paragraphs), with the Source that cites it."""
    return [(s, p) for s in context.sources for p in s.text.split("\n[…]\n")]


def test_a_chunk_repeated_across_a_companys_filings_is_stored_once_with_every_filing(
    tmp_path, indexed_filings
):
    ids = ("TSLA_10-K_2024-12-31", "TSLA_10-K_2025-12-31")
    filings = [_filing(indexed_filings, i) for i in ids]
    alone = {
        f.filing_id: {c["text"] for c in _chunks(build_index([f], tmp_path / f"{f.filing_id}.db"))}
        for f in filings
    }
    shared = alone[ids[0]] & alone[ids[1]]
    assert any("Cybersecurity Risk Management and Strategy" in t for t in shared)

    path = build_index(filings, tmp_path / "both.sqlite")

    db = sqlite3.connect(path)
    stored = db.execute("SELECT id, text FROM chunks").fetchall()
    listed: dict[int, set[str]] = {}
    for chunk_id, filing_id in db.execute("SELECT chunk_id, filing_id FROM chunk_filings"):
        listed.setdefault(chunk_id, set()).add(filing_id)
    db.close()
    texts = [text for _, text in stored]
    assert len(texts) == len(set(texts)) == len(alone[ids[0]] | alone[ids[1]])
    assert all(listed[i] == {f for f in ids if text in alone[f]} for i, text in stored)


def test_every_company_stores_each_text_once(index):
    db = sqlite3.connect(index)
    stored_twice = db.execute(
        "SELECT COUNT(*) FROM (SELECT 1 FROM chunks GROUP BY ticker, kind, text "
        "HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    in_several_filings = db.execute(
        "SELECT COUNT(*) FROM (SELECT 1 FROM chunk_filings GROUP BY chunk_id "
        "HAVING COUNT(DISTINCT filing_id) > 1)"
    ).fetchone()[0]
    db.close()

    assert stored_twice == 0
    assert in_several_filings > 100


@pytest.mark.parametrize(
    "question",
    [
        "What does Apple say about competition?",
        "What does Tesla say about Gigafactory Texas?",
        "How did Apple and Tesla describe demand over the past three years?",
    ],
)
def test_retrieved_chunks_hold_no_near_duplicate_of_a_more_recent_one(index, question):
    passages = _passages(_ask(index, question))

    assert len({s.filing_id for s, _ in passages}) > 1
    for source, passage in passages:
        own = _shingles(passage)
        newer = set().union(
            *(
                _shingles(p)
                for s, p in passages
                if s.ticker == source.ticker and s.report_period > source.report_period
            )
        )
        assert len(own & newer) < NEAR_DUPLICATE * len(own), (source.filing_id, passage[:80])


def _citing(context, phrase):
    return {s.filing_id for s, p in _passages(context) if phrase in re.sub(r"\s+", " ", p).lower()}


# Tesla's 10-Ks for FY2023 to FY2025 open Item 1C with the same passage: word for word in
# FY2024 and FY2025, and in FY2023 short of one space ("CYBERSECURITYCybersecurity").
CYBERSECURITY = "cybersecurity risk management and strategy"


def test_a_repeated_passage_is_cited_from_the_most_recent_filing(index):
    context = _ask(index, "What does Tesla say about cybersecurity management and strategy?")

    assert context.query_scope.periods == ()
    assert _citing(context, CYBERSECURITY) == {"TSLA_10-K_2025-12-31"}


@pytest.mark.parametrize(
    ("period", "filing_id"),
    [("fiscal 2024", "TSLA_10-K_2024-12-31"), ("FY2023", "TSLA_10-K_2023-12-31")],
)
def test_a_repeated_passage_is_cited_from_the_period_the_question_names(index, period, filing_id):
    context = _ask(
        index, f"What did Tesla say about cybersecurity management and strategy in {period}?"
    )

    assert _citing(context, CYBERSECURITY) == {filing_id}


@pytest.mark.parametrize(
    ("question", "periods"),
    [
        ("What did Apple report for FY2024?", ("FY2024",)),
        ("What did Apple report in fiscal year 2024?", ("FY2024",)),
        ("What did Apple report in Q2 FY2025?", ("Q2 FY2025",)),
        ("What did Apple report in 2023 and 2024?", ("FY2023", "FY2024")),
        ("What did Apple report?", ()),
    ],
)
def test_periods_named_in_a_question_are_read_as_fiscal_periods(index, question, periods):
    assert _ask(index, question).query_scope.periods == periods


# --- "How has it changed" routing ----------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "change"),
    [
        ("How have Tesla's risk factors changed over the last two years?", True),
        ("What changed in Apple's risk factors?", True),
        ("How has NVIDIA's revenue evolved?", True),
        ("What is new in Tesla's latest risk factors?", True),
        ("How do Tesla's risks differ from last year?", True),
        ("How did Tesla's risk factors change over the last two years?", True),
        ("How did that change?", True),
        ("What are Tesla's risk factors?", False),
        ("What does Tesla say about climate change?", False),
    ],
)
def test_change_questions_are_recognised(index, question, change):
    assert _ask(index, question).query_scope.change is change


def _new_text(indexed_filings, ticker):
    """For each of the Company's Filings, a function telling whether a passage is new:
    whether at least half its shingles are absent from the previous Filing of the same
    Form Type."""
    previous: dict[str, set] = {}
    last: dict[str, set] = {}
    for filing in sorted(
        (f for f in indexed_filings if f.ticker == ticker), key=lambda f: f.report_period
    ):
        previous[filing.filing_id] = last.get(filing.form_type, set())
        last[filing.form_type] = _shingles(filing.body)

    def is_new(source, passage):
        own = _shingles(passage)
        return len(own - previous[source.filing_id]) >= len(own) / 2

    return is_new


def test_a_change_question_retrieves_paragraphs_new_between_the_compared_periods(
    index, indexed_filings
):
    is_new = _new_text(indexed_filings, "TSLA")

    change = _passages(
        _ask(index, "How have Tesla's risk factors changed over the last two years?")
    )
    plain = _passages(_ask(index, "What are Tesla's risk factors over the last two years?"))

    new = [(s, p) for s, p in change if is_new(s, p)]
    assert {s.filing_id for s, _ in new} >= {"TSLA_10-K_2024-12-31", "TSLA_10-K_2025-12-31"}
    assert len(new) / len(change) > 2 * sum(is_new(s, p) for s, p in plain) / len(plain)
    assert {s.section for s, _ in change} == {"Risk Factors"}


def test_a_new_paragraph_is_cited_from_the_filing_it_first_appears_in(index, indexed_filings):
    is_new = _new_text(indexed_filings, "TSLA")
    later = _shingles(_filing(indexed_filings, "TSLA_10-K_2025-12-31").body)

    context = _ask(index, "How have Tesla's risk factors changed over the last two years?")

    # New in the FY2024 10-K and still in the FY2025 10-K: a plain question would cite the
    # FY2025 copy, but a change question cites the Filing that added it.
    kept = [
        p
        for s, p in _passages(context)
        if s.filing_id == "TSLA_10-K_2024-12-31"
        and is_new(s, p)
        and len(_shingles(p) & later) >= NEAR_DUPLICATE * len(_shingles(p))
    ]
    assert kept


# --- Sector phrases ----------------------------------------------------------------------

PHARMA_QUESTION = "What regulatory risks do the major pharmaceutical companies face?"
PHARMA = ["JNJ", "LLY", "MRK", "PFE", "ABBV"]


@pytest.mark.parametrize(
    ("question", "tickers"),
    [
        (PHARMA_QUESTION, PHARMA),
        ("What are the main risks facing the major banks?", ["BAC", "JPM"]),
        ("How do the oil majors describe climate regulation?", ["CVX", "XOM"]),
        ("What do the big drugmakers say about drug pricing?", PHARMA),
        ("What do oil and gas companies say about energy transition?", ["CVX", "XOM"]),
    ],
)
def test_a_sector_phrase_resolves_through_the_sector_table(sector_index, question, tickers):
    context = _ask(sector_index, question)

    assert [c.ticker for c in context.query_scope.companies] == tickers
    assert {s.ticker for s in context.sources} == set(tickers)


def test_a_resolved_sector_phrase_records_the_phrase_and_the_table_rows_it_used(sector_index):
    context = _ask(sector_index, PHARMA_QUESTION)

    [phrase] = context.query_scope.sector_phrases
    assert phrase.phrase == "pharmaceutical companies"
    assert phrase.column == "industry"
    assert phrase.values == ("Pharmaceuticals", "Biotechnology")
    assert phrase.tickers == tuple(PHARMA)


def test_the_prompt_tells_the_answer_to_name_the_companies_a_sector_phrase_resolved_to(
    sector_index,
):
    context = _ask(sector_index, PHARMA_QUESTION)

    system, user = context.messages
    assert "Sector table" in system.content
    resolved = user.content.split("# Sources")[0]
    assert '"pharmaceutical companies"' in resolved
    for name in ("Johnson & Johnson", "Eli Lilly and Company", "Merck", "Pfizer", "AbbVie"):
        assert name in resolved
    assert "Thermo Fisher" not in resolved and "UnitedHealth" not in resolved


def test_a_question_with_no_sector_phrase_has_no_resolution_block(sector_index):
    context = _ask(sector_index, "What are the main risks facing Pfizer?")

    assert context.query_scope.sector_phrases == ()
    assert "Sector table" not in context.messages[1].content


def test_a_named_company_and_a_sector_phrase_cover_both_without_repeats(sector_index):
    question = "How does Pfizer's pricing risk compare with the other pharmaceutical companies?"

    context = _ask(sector_index, question)

    assert [c.ticker for c in context.query_scope.companies] == [
        "PFE",
        "JNJ",
        "LLY",
        "MRK",
        "ABBV",
    ]


@pytest.mark.parametrize(
    ("question", "tickers"),
    [
        ("What does Bank of America say about credit risk?", ["BAC"]),
        ("How do central banks' rate decisions affect JPMorgan?", ["JPM"]),
        ("What does Goldman Sachs say about investment banks' competition?", ["GS"]),
        ("What does Merck say about its biggest pharmaceutical product?", ["MRK"]),
        ("What does Exxon say about oil prices?", ["XOM"]),
    ],
)
def test_words_that_only_mention_a_sector_are_not_sector_phrases(sector_index, question, tickers):
    context = _ask(sector_index, question)

    assert [c.ticker for c in context.query_scope.companies] == tickers
    assert context.query_scope.sector_phrases == ()


# --- Company Groups ----------------------------------------------------------------------

BIG_TECH_QUESTION = "What are the main AI risks for big tech companies?"
BIG_TECH = ["AAPL", "AMZN", "GOOG", "META", "MSFT", "NVDA", "TSLA"]


def test_big_tech_resolves_to_the_curated_company_group(big_tech_index):
    context = _ask(big_tech_index, BIG_TECH_QUESTION)

    assert [c.ticker for c in context.query_scope.companies] == BIG_TECH
    assert {s.ticker for s in context.sources} == set(BIG_TECH)
    [group] = context.query_scope.sector_phrases
    assert group.phrase == "big tech companies"
    assert group.column == "group"
    assert group.is_company_group
    assert group.values == ("Big Tech",)
    assert group.tickers == tuple(BIG_TECH)


@pytest.mark.parametrize(
    "question",
    [
        "How do the megacap tech companies describe competition?",
        "What does Big Tech say about AI regulation?",
        "What are the risk factors of the megacap tech names?",
    ],
)
def test_megacap_tech_and_big_tech_alone_name_the_same_group(big_tech_index, question):
    context = _ask(big_tech_index, question)

    assert [c.ticker for c in context.query_scope.companies] == BIG_TECH
    assert [p.column for p in context.query_scope.sector_phrases] == ["group"]


def test_tech_companies_still_resolve_to_the_information_technology_sector(big_tech_index):
    context = _ask(big_tech_index, "What are the main AI risks for tech companies?")

    [phrase] = context.query_scope.sector_phrases
    assert (phrase.column, phrase.values) == ("sector", ("Information Technology",))
    assert not phrase.is_company_group
    assert {c.ticker for c in context.query_scope.companies} == {
        "AAPL",
        "ADBE",
        "CSCO",
        "IBM",
        "MSFT",
        "NVDA",
    }


def test_the_prompt_names_a_company_group_as_a_curated_group(big_tech_index):
    context = _ask(big_tech_index, BIG_TECH_QUESTION)

    in_scope = context.messages[1].content.split("# Companies in scope")[1].split("# ")[0]
    assert '"big tech companies"' in in_scope
    assert 'curated Company Group "Big Tech"' in in_scope
    for name in ("Apple Inc", "Amazon", "Alphabet", "Meta Platforms", "Microsoft", "NVIDIA"):
        assert name in in_scope
    assert "Tesla" in in_scope
    assert "Adobe" not in in_scope and "Cisco" not in in_scope


def test_the_index_carries_each_companys_group(big_tech_index):
    db = sqlite3.connect(big_tech_index)
    groups = dict(db.execute("SELECT ticker, company_group FROM companies"))
    db.close()

    assert {t for t, g in groups.items() if g == "Big Tech"} == set(BIG_TECH)
    assert groups["ADBE"] is None and groups["IBM"] is None


def test_an_index_built_before_company_groups_is_refused(tmp_path, big_tech_index):
    old = tmp_path / "old.sqlite"
    old.write_bytes(big_tech_index.read_bytes())
    db = sqlite3.connect(old)
    db.execute("PRAGMA user_version = 5")
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="make index"):
        _ask(old, BIG_TECH_QUESTION)


# --- Metric ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "metric"),
    [
        ("How has NVIDIA's revenue changed over the last two years?", "revenue"),
        ("How have Apple's sales grown?", "revenue"),
        ("What drove Tesla's top line in 2025?", "revenue"),
        ("How has Tesla's net income changed over three years?", "net_income"),
        ("Were NVIDIA's earnings up last year?", "net_income"),
        ("Is Target's profit growing?", "net_income"),
        ("What are Apple's main risk factors?", None),
    ],
)
def test_metric_words_name_the_metric_of_the_query_scope(index, question, metric):
    assert _ask(index, question).query_scope.metric == metric


# --- Coverage Gaps -----------------------------------------------------------------------

JPM_FILINGS = (
    "JPM_10-Q_2025-03-31",
    "JPM_10-Q_2025-06-30",
    "JPM_10-Q_2025-09-30",
    "JPM_10-K_2025-12-31",
)
GE_FILING = "GE_10-K_2014-12-31"


def _gaps(context, kind):
    return [g for g in context.coverage_gaps if g.kind == kind]


def _section(prompt, heading):
    """The text of one `# heading` block of the prompt's user message."""
    match = re.search(rf"^# {re.escape(heading)}\n\n(.*?)(?=^# |\Z)", prompt, re.M | re.S)
    assert match, f"no '# {heading}' block in the prompt"
    return match.group(1)


def test_a_trend_asked_of_a_snapshot_company_names_the_filings_the_corpus_holds(index):
    context = _ask(index, "How has JPMorgan's revenue trended over the last three years?")

    [gap] = _gaps(context, "snapshot_trend")
    assert gap.companies == ("JPM",)
    assert gap.text.startswith("Trend unavailable: JPMorgan Chase is a Snapshot Company.")
    assert all(filing_id in gap.text for filing_id in JPM_FILINGS)
    assert "Q1 FY2025 to FY2025" in gap.text
    assert "2025-03-31 to 2025-12-31 only" in gap.text
    assert gap.text in _section(context.messages[1].content, "Coverage Gaps")


@pytest.mark.parametrize(
    "question",
    [
        "How have JPMorgan's risk factors changed?",
        "How has JPMorgan's net income evolved over the past two years?",
        "What is the trend in JPMorgan's credit card lending?",
    ],
)
def test_change_and_multi_period_questions_ask_a_snapshot_company_for_a_trend(index, question):
    assert [g.companies for g in _gaps(_ask(index, question), "snapshot_trend")] == [("JPM",)]


@pytest.mark.parametrize(
    "question",
    [
        "What are JPMorgan's main risk factors?",
        "What did JPMorgan report in its latest 10-K?",
        "How do Apple's and JPMorgan's risk factors differ?",
        "How has NVIDIA's revenue changed over the last two years?",
    ],
)
def test_point_in_time_questions_and_tracked_trends_have_no_trend_gap(index, question):
    assert _gaps(_ask(index, question), "snapshot_trend") == []


def test_a_company_missing_from_the_corpus_is_named_and_the_rest_answered(gap_index):
    context = _ask(gap_index, "Compare Wells Fargo and Bank of America's capital positions")

    assert [c.ticker for c in context.query_scope.companies] == ["BAC"]
    assert context.query_scope.missing_companies == ("Wells Fargo",)
    [gap] = _gaps(context, "missing_company")
    assert gap.companies == ("Wells Fargo",)
    assert gap.text == (
        "Not in the Corpus: Wells Fargo is not in the Filings provided, so this answer "
        "does not cover it."
    )
    assert context.sources
    assert {s.ticker for s in context.sources} == {"BAC"}
    assert gap.text in _section(context.messages[1].content, "Coverage Gaps")


def test_a_question_about_only_missing_companies_retrieves_nothing(index):
    context = _ask(index, "What are Citigroup's main risk factors?")

    assert context.query_scope.companies == ()
    assert context.query_scope.missing_companies == ("Citigroup",)
    assert context.sources == ()
    assert [g.companies for g in _gaps(context, "missing_company")] == [("Citigroup",)]


@pytest.mark.parametrize(
    ("question", "missing"),
    [
        ("What risks do Merck and Bristol-Myers Squibb face?", ("Bristol Myers Squibb",)),
        ("How does WFC compare with JPM?", ("Wells Fargo",)),
        ("Compare Citi, Amgen and Honeywell", ("Citigroup", "Amgen", "Honeywell")),
        ("What does Apple say about shell companies?", ()),
        ("What are Apple's main risk factors?", ()),
    ],
)
def test_missing_companies_are_recognised_by_name_alias_and_ticker(index, question, missing):
    assert _ask(index, question).query_scope.missing_companies == missing


def test_the_curated_missing_companies_are_none_of_the_corpus_companies():
    from edgar_rag.corpus import load_sector_table
    from edgar_rag.retrieval import load_missing_companies

    missing = load_missing_companies()
    in_corpus = {row.ticker for row in load_sector_table()}
    names = [m.name for m in missing]
    assert len(names) == len(set(names)) >= 20
    assert not in_corpus & {m.ticker for m in missing}
    assert {"Wells Fargo", "Citigroup", "Bristol Myers Squibb", "Amgen", "Honeywell"} <= set(names)


def test_general_electric_today_is_answered_without_ge_capitals_stale_filing(gap_index):
    context = _ask(gap_index, "How has General Electric performed recently?")

    assert [c.ticker for c in context.query_scope.companies] == ["GE"]
    assert context.sources == ()
    assert GE_FILING not in {f.filing_id for f in context.query_scope.filings}
    [gap] = _gaps(context, "stale_filing")
    assert gap.companies == ("GE",)
    assert gap.text == (
        "Stale Filing: the only General Electric Filing is GE Capital's 10-K for FY2014 "
        "(Report Period 2014-12-31); it does not describe General Electric today, so it is "
        "left out of this answer."
    )
    assert gap.text in _section(context.messages[1].content, "Coverage Gaps")


def test_the_stale_filing_is_left_out_of_a_question_naming_no_company(gap_index):
    context = _ask(gap_index, "Which companies are reducing the size of their balance sheet?")

    assert context.sources
    assert GE_FILING not in {s.filing_id for s in context.sources}


def test_ge_capitals_2014_report_asked_for_by_name_is_cited_and_still_flagged(gap_index):
    context = _ask(
        gap_index,
        "What did GE Capital's 2014 annual report say about reducing the size of its "
        "balance sheet?",
    )

    assert {s.filing_id for s in context.sources} == {GE_FILING}
    [gap] = _gaps(context, "stale_filing")
    assert gap.text.endswith(
        "it does not describe General Electric today, so it is cited here only as GE "
        "Capital's report for FY2014."
    )


@pytest.mark.parametrize(
    ("question", "left_out"),
    [
        ("How has General Electric performed recently?", True),
        ("What are GE's main risk factors?", True),
        ("What did GE say about its balance sheet?", True),
        ("What did GE Capital say about its balance sheet?", False),
        ("What did General Electric Capital say about its balance sheet?", False),
        ("What did General Electric say about its balance sheet in FY2014?", False),
        ("What did General Electric say about its balance sheet in 2014?", False),
    ],
)
def test_the_ge_capital_filing_is_left_out_unless_asked_for_by_name_or_period(
    gap_index, question, left_out
):
    """Assumption 3: the stale Filing is left out of answers about General Electric,
    except when the question asks for GE Capital by name or names the period it covers.
    Left out, it is neither in the Query Scope nor cited; asked for, it is both."""
    context = _ask(gap_index, question)

    [ge] = context.coverage
    assert [f.filing_id for f in ge.left_out] == ([GE_FILING] if left_out else [])
    in_scope = {f.filing_id for f in context.query_scope.filings}
    cited = {s.filing_id for s in context.sources}
    assert (GE_FILING in in_scope, GE_FILING in cited) == (not left_out, not left_out)
    [gap] = _gaps(context, "stale_filing")
    assert gap.text.endswith("left out of this answer.") == left_out


@pytest.mark.parametrize(
    ("question", "left_out"),
    [
        ("Which companies are reducing the size of their balance sheet?", True),
        ("Which companies were reducing the size of their balance sheet in 2014?", False),
    ],
)
def test_a_question_naming_no_company_is_held_away_from_a_left_out_stale_filing(
    gap_index, question, left_out
):
    """A question naming no Company searches every Filing. When the stale Filing is left
    out, retrieval is held to the remaining Filings, so it cannot be cited. When the
    question names the period it covers, nothing is left out, retrieval is not held and
    the stale Filing may be cited. Holding retrieval only when a Filing is left out is
    the intent (assumption 3): with nothing left out, holding it to every Filing would
    change nothing."""
    context = _ask(gap_index, question)

    assert context.query_scope.companies == ()
    assert "BAC" in {s.ticker for s in context.sources}
    assert (GE_FILING in {s.filing_id for s in context.sources}) is not left_out


@pytest.mark.parametrize(
    "question",
    [
        "What is Tesla's outlook for 2026?",
        "What guidance has Tesla given for deliveries?",
        "What does Tesla expect for next year?",
    ],
)
def test_an_outlook_question_states_that_guidance_is_not_in_the_filings(index, question):
    context = _ask(index, question)

    [gap] = _gaps(context, "no_guidance")
    assert gap.companies == ("TSLA",)
    assert gap.text == (
        "No guidance in the Filings: Tesla's own guidance is not in the Filings provided; "
        "the outlook below is drawn from MD&A commentary and risk factors."
    )


def test_a_question_that_is_not_about_the_outlook_has_no_guidance_gap(index):
    assert _gaps(_ask(index, "What are Tesla's main risk factors?"), "no_guidance") == []


def test_compared_companies_whose_latest_filings_cover_different_periods_are_flagged(index):
    context = _ask(index, BRIEF_QUESTION)

    [gap] = _gaps(context, "periods_differ")
    assert gap.companies == ("AAPL", "TSLA", "JPM")
    assert gap.text.startswith("Periods differ:")
    assert "Apple: 10-K FY2025, year to 2025-09-27" in gap.text
    assert "Tesla: 10-K FY2025, year to 2025-12-31" in gap.text
    assert "JPMorgan Chase: 10-K FY2025, year to 2025-12-31" in gap.text


def test_a_single_company_question_has_no_periods_gap(index):
    assert _gaps(_ask(index, "What are Apple's main risk factors?"), "periods_differ") == []


def test_the_prompt_gives_each_companys_coverage_report_periods_and_fiscal_periods(index):
    context = _ask(index, BRIEF_QUESTION)
    coverage = _section(context.messages[1].content, "Coverage")

    assert "Apple Inc (AAPL): Tracked Company" in coverage
    assert "Tesla Inc (TSLA): Tracked Company" in coverage
    assert "JPMorgan Chase & Co (JPM): Snapshot Company" in coverage
    for company in context.coverage:
        assert company.in_scope
        for filing in company.in_scope:
            assert (
                f"{filing.filing_id} ({filing.form_type} {filing.fiscal_period}, "
                f"{filing_months(filing.report_period, filing.form_type)}, "
                f"Report Period {filing.report_period})"
            ) in coverage


@pytest.fixture(scope="module")
def msft_index(tmp_path_factory):
    """Microsoft's Filings from FY2025 on: its fiscal year ends in June."""
    from datetime import date

    from edgar_rag.corpus import load_corpus
    from edgar_rag.retrieval import build_index

    filings = [
        f for f in load_corpus() if f.ticker == "MSFT" and f.report_period >= date(2024, 9, 1)
    ]
    return build_index(filings, tmp_path_factory.mktemp("msft_index") / "edgar_rag.sqlite")


@pytest.mark.parametrize(
    ("question", "company_line", "filings"),
    [
        # NVIDIA's 52/53-week year ends in late January: FY2026's second quarter is
        # May to July 2025, and FY2025 ran from February 2024 to January 2025.
        (
            "How has NVIDIA's revenue changed over the last two years?",
            "NVIDIA Corporation (NVDA): Tracked Company; fiscal year ends in January",
            [
                "NVDA_10-K_2025-01-26 (10-K FY2025, Feb 2024–Jan 2025, Report Period 2025-01-26)",
                "NVDA_10-Q_2025-07-27 (10-Q Q2 FY2026, May–Jul 2025, Report Period 2025-07-27)",
                "NVDA_10-Q_2025-10-26 (10-Q Q3 FY2026, Aug–Oct 2025, Report Period 2025-10-26)",
            ],
        ),
        # Apple's year ends in late September: its first quarter is October to December.
        (
            BRIEF_QUESTION,
            "Apple Inc (AAPL): Tracked Company; fiscal year ends in September",
            [
                "AAPL_10-K_2025-09-27 (10-K FY2025, Oct 2024–Sep 2025, Report Period 2025-09-27)",
                "AAPL_10-Q_2025-12-27 (10-Q Q1 FY2026, Oct–Dec 2025, Report Period 2025-12-27)",
            ],
        ),
        # Tesla's year is the calendar year.
        (
            "How has Tesla's revenue changed over the last two years?",
            "Tesla Inc (TSLA): Tracked Company; fiscal year ends in December",
            [
                "TSLA_10-K_2025-12-31 (10-K FY2025, Jan–Dec 2025, Report Period 2025-12-31)",
                "TSLA_10-Q_2025-06-30 (10-Q Q2 FY2025, Apr–Jun 2025, Report Period 2025-06-30)",
            ],
        ),
    ],
)
def test_the_coverage_block_gives_each_filings_calendar_months(
    index, question, company_line, filings
):
    coverage = _section(_ask(index, question).messages[1].content, "Coverage")

    assert company_line in coverage
    for filing in filings:
        assert filing in coverage


def test_the_coverage_block_gives_calendar_months_for_a_june_year_end(msft_index):
    """Microsoft's year ends on June 30: FY2026's first quarter is July to September 2025."""
    coverage = _section(
        _ask(msft_index, "What are Microsoft's main risk factors?").messages[1].content,
        "Coverage",
    )

    assert "Microsoft Corporation (MSFT): Tracked Company; fiscal year ends in June" in coverage
    assert (
        "MSFT_10-K_2025-06-30 (10-K FY2025, Jul 2024–Jun 2025, Report Period 2025-06-30)"
    ) in coverage
    assert (
        "MSFT_10-Q_2025-09-30 (10-Q Q1 FY2026, Jul–Sep 2025, Report Period 2025-09-30)"
    ) in coverage
    assert (
        "MSFT_10-Q_2025-12-31 (10-Q Q2 FY2026, Oct–Dec 2025, Report Period 2025-12-31)"
    ) in coverage


def test_the_prompt_asks_for_calendar_months_beside_a_non_december_fiscal_period(index):
    """Prompt v15: the first time the answer names a fiscal period of a Company whose year
    doesn't end in December, it gives the calendar months the Coverage block lists."""
    context = _ask(index, "How has NVIDIA's revenue changed over the last two years?")
    rules = " ".join(context.messages[0].content.split())

    assert (
        "The first time the answer names a fiscal period of a Company whose fiscal year "
        "does not end in December, give its calendar months after it"
    ) in rules
    assert 'copied from "Coverage"' in rules
    assert '"Q2 FY2026 (May–Jul 2025)"' in rules


def test_each_source_label_carries_its_calendar_months(index):
    context = _ask(index, "How has NVIDIA's revenue changed over the last two years?")
    user = context.messages[1].content
    labels = {s.filing_id: s.label for s in context.sources}

    assert labels["NVDA_10-Q_2025-07-27"].startswith("NVDA 10-Q Q2 FY2026 (May–Jul 2025), ")
    assert labels["NVDA_10-K_2025-01-26"].startswith("NVDA 10-K FY2025 (Feb 2024–Jan 2025), ")
    for source in context.sources:
        assert f"[{source.tag}] {source.label}" in user
    # The Financial Facts rows give the months beside each fiscal period too, a derived
    # fourth quarter included.
    facts = _section(user, "Financial Facts")
    assert "| NVDA | Revenue | Q3 FY2026 (Aug–Oct 2025) | 3 months ended 2025-10-26 |" in facts
    assert "| NVDA | Revenue | Q4 FY2025 (Nov 2024–Jan 2025) | " in facts


def test_the_prompt_says_what_the_stale_filing_is_in_the_coverage_block(gap_index):
    context = _ask(gap_index, "How has General Electric performed recently?")
    coverage = _section(context.messages[1].content, "Coverage")

    assert "General Electric Company (GE): Snapshot Company" in coverage
    assert f"left out: {GE_FILING}" in coverage


def test_a_question_with_no_gaps_says_so_in_the_prompt(index):
    context = _ask(index, "What are Apple's main risk factors?")

    assert context.coverage_gaps == ()
    assert _section(context.messages[1].content, "Coverage Gaps").strip() == "None."


def test_the_prompt_asks_for_a_gap_only_where_it_leaves_part_of_the_question_unanswered(index):
    """Prompt v15 (ADR 0016): the product shows every Coverage Gap as a Coverage note, so
    the answer no longer recites the gap wordings near its start or in a closing Coverage
    note; it says so in its own words where a gap leaves part of the question unanswered,
    and still never fills one."""
    context = _ask(index, "Compare the risk factors of JPMorgan and Wells Fargo.")
    system, user = (m.content for m in context.messages)
    rules = " ".join(system.split())

    # The gaps still reach the prompt, so the answer knows what it cannot cover.
    assert "Wells Fargo is not in the Filings provided" in _section(user, "Coverage Gaps")
    assert "in your own words" in rules
    assert "leaves part of the question unanswered" in rules
    assert "Never fill a gap from general knowledge" in rules
    assert "shown below your answer" in rules
    assert "Never mention that the companies' periods differ for its own sake" in rules
    # Nothing asks for the fixed wordings near the start or a closing Coverage note.
    assert "in the words given" not in rules
    assert "near the start of the answer. Never fill" not in rules
    assert 'end with a short "Coverage" note' not in rules
    assert "repeat the Coverage Gaps" not in rules
    assert "report for different periods" not in rules


def test_the_prompt_asks_for_a_comparison_table_whenever_companies_are_compared(index):
    context = _ask(index, BRIEF_QUESTION)
    rules = " ".join(context.messages[0].content.split())

    assert (
        "When the question compares two or more Companies on the same dimensions, give a "
        "comparison table first"
    ) in rules
    assert "then each Company's detail under its own heading" in rules


def test_coverage_gaps_are_worded_the_same_way_every_time(index, gap_index):
    first = _ask(index, "How has JPMorgan's revenue changed over the last two years?")
    again = _ask(index, "Has JPMorgan's net income changed over the past three years?")

    assert _gaps(first, "snapshot_trend") == _gaps(again, "snapshot_trend")


# --- A ranker in place of bm25() (the challenger Arms) -----------------------------------


class _Recorder:
    """A ranker that records what it was asked and ranks by a given rule."""

    def __init__(self, rank=lambda request: request.lexical):
        self.requests = []
        self.rank = rank

    def __call__(self, request):
        self.requests.append(request)
        return self.rank(request)


def _chunk_ids(index, **where):
    return {row["id"] for row in _chunks(index, **where) if row["kind"] != "risk_pointer"}


def test_a_ranker_sees_only_the_chunks_inside_the_hard_filters(index):
    ranker = _Recorder()

    prepare_answer_context(
        [Message("user", "What are Tesla's risk factors?")], index, ranker=ranker
    )

    (request,) = ranker.requests
    assert request.ticker == "TSLA"
    assert "Tesla's risk factors" in request.question
    # The latest window: Tesla's FY2025 10-K, which no 10-Q follows, in its Risk Factors.
    assert set(request.eligible) == _chunk_ids(
        index, filing_id="TSLA_10-K_2025-12-31", section="Risk Factors"
    )
    assert request.lexical and set(request.lexical) <= set(request.eligible)


def test_the_lexical_ranking_given_to_a_ranker_is_the_shipped_ranking(index):
    question = "What does Tesla say about Gigafactory Texas?"

    shipped = _ask(index, question)
    reranked = prepare_answer_context([Message("user", question)], index, ranker=_Recorder())

    assert reranked.sources == shipped.sources


def test_a_ranker_can_reorder_and_rank_chunks_the_terms_do_not_match(index):
    question = "What does Tesla say about Gigafactory Texas?"
    shipped = _ask(index, question)

    reversed_ = prepare_answer_context(
        [Message("user", question)],
        index,
        ranker=_Recorder(lambda r: list(reversed(r.eligible))),
    )

    assert reversed_.sources and reversed_.sources != shipped.sources
    assert {s.ticker for s in reversed_.sources} == {"TSLA"}
    assert not all("Texas" in s.text for s in reversed_.sources)


def test_a_ranker_cannot_reach_outside_the_hard_filters(index):
    outside = sorted(_chunk_ids(index, filing_id="AAPL_10-K_2025-09-27"))

    context = prepare_answer_context(
        [Message("user", "What are Tesla's risk factors?")],
        index,
        ranker=_Recorder(lambda r: outside + list(r.lexical)),
    )

    assert {s.ticker for s in context.sources} == {"TSLA"}
    assert {s.section for s in context.sources} == {"Risk Factors"}
