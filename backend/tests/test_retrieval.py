"""Tests through the retrieval seam: build an index from real Corpus Filings, then
prepare Answer Contexts from conversations."""

import re
import sqlite3

import pytest

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
    assert source.label.startswith(f"TSLA {source.form_type} {source.fiscal_period}, ")


def test_the_prompt_renders_rules_sources_and_question(index):
    context = _ask(index, BRIEF_QUESTION)

    assert context.prompt_version == PROMPT_VERSION == "v7"
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


def test_a_question_with_no_search_terms_gets_no_sources(index):
    context = _ask(index, "What about Apple?")

    assert [c.ticker for c in context.query_scope.companies] == ["AAPL"]
    assert context.sources == ()
    assert "No Sources were found" in context.messages[1].content


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
        ("What legal proceedings does Apple disclose in its latest Filings?", "Legal Proceedings"),
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


def test_a_stub_section_falls_back_to_the_whole_filing(index):
    stub = _chunks(index, filing_id="TSLA_10-K_2025-12-31", section="Legal Proceedings")
    assert sum(c["tokens"] for c in stub) < STUB_TOKENS  # "see Note 15" and little else

    context = _ask(index, "What legal proceedings does Tesla disclose in its latest Filings?")

    assert context.query_scope.sections == ("Legal Proceedings",)
    assert {s.filing_id for s in context.sources} == {"TSLA_10-K_2025-12-31"}
    assert {s.section for s in context.sources} - {"Legal Proceedings"}


def test_a_missing_section_falls_back_to_the_whole_filing(index):
    assert not _chunks(index, filing_id="JPM_10-Q_2025-09-30", section="MD&A")

    context = _ask(
        index, "What does JPMorgan's MD&A say about net interest income in the last two quarters?"
    )

    assert _scope_filings(context, "JPM") == ["JPM_10-Q_2025-09-30", "JPM_10-K_2025-12-31"]
    assert "JPM_10-Q_2025-09-30" in {s.filing_id for s in context.sources}
    assert {s.section for s in context.sources} - {"MD&A"}


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
    stub = _ask(index, "What legal proceedings does Tesla disclose in its latest Filings?")
    unhinted = _ask(index, "How does Apple describe its services business?")

    assert _searched(stub) == [("TSLA", "TSLA_10-K_2025-12-31", None)]
    assert _searched(unhinted) == [
        ("AAPL", f.filing_id, None) for f in unhinted.query_scope.filings
    ]
    assert len(_searched(unhinted)) == 16


def test_a_question_naming_no_company_records_every_filing_searched_whole(index, indexed_filings):
    context = _ask(index, "Which companies discuss artificial intelligence?")

    assert {(p.filing_id, p.section) for p in context.query_scope.searched} == {
        (f.filing_id, None) for f in indexed_filings
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


def test_an_index_built_by_an_older_version_says_to_rebuild_it(tmp_path, index):
    old = tmp_path / "old.sqlite"
    old.write_bytes(index.read_bytes())
    db = sqlite3.connect(old)
    db.execute("PRAGMA user_version = 1")
    db.commit()
    db.close()

    with pytest.raises(RuntimeError, match="make index"):
        _ask(old, BRIEF_QUESTION)


# --- Deduplication -----------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")


def _shingles(text):
    """8-word shingles, the EDA's measure of repeated text (notebook section 6)."""
    words = _WORD.findall(text.lower())
    return {tuple(words[i : i + 8]) for i in range(len(words) - 7)}


def _passages(context):
    """Each retrieved chunk, with the Source that cites it."""
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
                f"Report Period {filing.report_period})"
            ) in coverage


def test_the_prompt_says_what_the_stale_filing_is_in_the_coverage_block(gap_index):
    context = _ask(gap_index, "How has General Electric performed recently?")
    coverage = _section(context.messages[1].content, "Coverage")

    assert "General Electric Company (GE): Snapshot Company" in coverage
    assert f"left out: {GE_FILING}" in coverage


def test_a_question_with_no_gaps_says_so_in_the_prompt(index):
    context = _ask(index, "What are Apple's main risk factors?")

    assert context.coverage_gaps == ()
    assert _section(context.messages[1].content, "Coverage Gaps").strip() == "None."


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
