"""Tests through the retrieval seam: build an index from real Corpus Filings, then
prepare Answer Contexts from conversations."""

import re
import sqlite3

import pytest

from edgar_rag.retrieval import (
    CONTEXT_BUDGET_TOKENS,
    PROMPT_VERSION,
    Message,
    build_index,
    count_tokens,
    prepare_answer_context,
)

BRIEF_QUESTION = (
    "What are the primary risk factors facing Apple, Tesla, and JPMorgan, and how do they compare?"
)


def _chunks(index, **where):
    db = sqlite3.connect(index)
    db.row_factory = sqlite3.Row
    clause = " AND ".join(f"{k} = ?" for k in where) or "1"
    rows = db.execute(
        f"SELECT * FROM chunks WHERE {clause} ORDER BY filing_id, ordinal", tuple(where.values())
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

    assert dict(chunk) | {"id": None, "ordinal": None, "tokens": None, "text": None} == {
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


def test_risk_pointers_are_never_retrieved(index):
    context = _ask(index, "What are Apple's risk factors?")

    assert context.sources
    assert not any(
        s.filing_id == "AAPL_10-Q_2025-12-27" and s.section == "Risk Factors"
        for s in context.sources
    )


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

    assert context.prompt_version == PROMPT_VERSION == "v1"
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
