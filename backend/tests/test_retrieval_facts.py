"""Financial Facts in the Answer Context, through the retrieval seam: `build_index` writes
the ADR 0001 store beside the chunks, and `prepare_answer_context` puts the rows a
figure question asks for into the prompt, cited by one Source per Filing."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from edgar_rag.financial_facts import extract_financial_facts
from edgar_rag.retrieval import Message, build_index, prepare_answer_context

NVDA_TWO_YEARS = "How has NVIDIA's revenue changed over the last two years?"


def _ask(index, question):
    return prepare_answer_context([Message("user", question)], index)


def _store(index):
    db = sqlite3.connect(index)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT * FROM financial_facts").fetchall()
    db.close()
    return rows


def _user_prompt(context):
    return context.messages[-1].content


def _facts_section(context):
    prompt = _user_prompt(context)
    return prompt[prompt.index("# Financial Facts") : prompt.index("# Sources")]


def _source(context, tag):
    return next(s for s in context.sources if s.tag == tag)


@pytest.fixture(scope="module")
def segments_index(tmp_path_factory):
    """Disney reorganised its segments in FY2023; Coca-Cola stopped reporting Global
    Ventures as a segment in 2025."""
    from edgar_rag.corpus import load_corpus

    filings = [f for f in load_corpus() if f.ticker in {"DIS", "KO"}]
    return build_index(filings, tmp_path_factory.mktemp("segments") / "edgar_rag.sqlite")


# --- The store -------------------------------------------------------------------------


def test_the_index_holds_the_tracked_companies_financial_facts_as_extracted(index, indexed_filings):
    expected = {
        (fact.filing_id, fact.metric, fact.segment, fact.value, fact.label)
        for filing in indexed_filings
        if filing.coverage == "tracked"
        for fact in extract_financial_facts(filing)
    }

    stored = {
        (r["filing_id"], r["metric"], r["segment"], r["value"], r["label"]) for r in _store(index)
    }

    assert stored == expected
    assert ("NVDA_10-K_2025-01-26", "revenue", None, 130_497_000_000, "Revenue") in stored


def test_snapshot_companies_have_no_financial_facts_in_the_store(index):
    assert "JPM" not in {r["ticker"] for r in _store(index)}


def test_sec_xbrl_data_is_never_loaded_into_the_store():
    """The store is built from the Filings alone: building and reading the index never
    imports the SEC reference module or reads its cache."""
    code = "import sys, edgar_rag.retrieval\nprint('edgar_rag.sec_reference' in sys.modules)"
    loaded = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert loaded == "False"

    from edgar_rag import retrieval

    source = Path(retrieval.__file__).read_text(encoding="utf-8")
    assert "sec_reference" not in source
    assert "sec_companyfacts" not in source


# --- Figure questions ------------------------------------------------------------------

# NVIDIA's quarterly revenue in $ millions, as its 10-Qs report it, and its fourth
# quarters as each 10-K's year less the three 10-Q quarters of that fiscal year:
# FY2024 60,922 − (7,192 + 13,507 + 18,120); FY2025 130,497 − (26,044 + 30,040 + 35,082).
NVDA_QUARTERS = {
    "Q4 FY2024": ("22,103", None),
    "Q1 FY2025": ("26,044", "NVDA_10-Q_2024-04-28"),
    "Q2 FY2025": ("30,040", "NVDA_10-Q_2024-07-28"),
    "Q3 FY2025": ("35,082", "NVDA_10-Q_2024-10-27"),
    "Q4 FY2025": ("39,331", None),
    "Q1 FY2026": ("44,062", "NVDA_10-Q_2025-04-27"),
    "Q2 FY2026": ("46,743", "NVDA_10-Q_2025-07-27"),
    "Q3 FY2026": ("57,006", "NVDA_10-Q_2025-10-26"),
}


def test_the_last_two_years_of_nvidia_revenue_puts_eight_quarters_in_the_prompt(index):
    context = _ask(index, NVDA_TWO_YEARS)

    quarters = [
        r
        for r in context.financial_facts
        if r.ticker == "NVDA" and r.metric == "revenue" and r.months == 3
    ]
    assert [r.fiscal_period for r in quarters] == list(NVDA_QUARTERS)
    facts = _facts_section(context)
    for row in quarters:
        value, filing_id = NVDA_QUARTERS[row.fiscal_period]
        assert row.value == int(value.replace(",", "")) * 1_000_000
        cited = {_source(context, tag).filing_id for tag in row.sources}
        if filing_id:
            assert cited == {filing_id}
        line = next(
            line
            for line in facts.splitlines()
            if f"| {row.fiscal_period} (" in line and "Revenue |" in line
        )
        assert f"${value} million" in line
        assert all(f"[{tag}]" in line for tag in row.sources)


def test_each_facts_source_is_the_financial_facts_of_one_filing(index):
    context = _ask(index, NVDA_TWO_YEARS)

    facts = [s for s in context.sources if s.kind == "facts"]
    assert [s.number for s in facts] == list(range(1, len(facts) + 1))  # numbered first
    assert len({s.filing_id for s in facts}) == len(facts)
    assert {s.section for s in facts} == {"Financial Facts"}
    assert all(r.filing_id == s.filing_id for s in facts for r in s.facts)
    q3 = next(s for s in facts if s.filing_id == "NVDA_10-Q_2025-10-26")
    assert [(r.metric, r.value, r.label) for r in q3.facts] == [
        ("revenue", 57_006_000_000, "Revenue")
    ]
    assert q3.fiscal_period == "Q3 FY2026"
    # Text Sources are still retrieved, numbered after the Facts Sources.
    text = [s for s in context.sources if s.kind == "text"]
    assert text and min(s.number for s in text) == len(facts) + 1


def test_a_derived_fourth_quarter_is_labelled_derived_and_cites_the_filings_it_comes_from(
    index,
):
    context = _ask(index, NVDA_TWO_YEARS)

    q4 = next(
        r for r in context.financial_facts if r.fiscal_period == "Q4 FY2024" and r.months == 3
    )
    assert q4.filing_id is None and q4.label is None
    assert q4.derived == "FY2024 less Q1–Q3 FY2024"
    assert [_source(context, tag).filing_id for tag in q4.sources] == [
        "NVDA_10-K_2024-01-28",
        "NVDA_10-Q_2023-04-30",
        "NVDA_10-Q_2023-07-30",
        "NVDA_10-Q_2023-10-29",
    ]
    line = next(line for line in _facts_section(context).splitlines() if "| Q4 FY2024 (" in line)
    assert "derived" in line.lower()


def test_a_year_on_year_change_is_derived_from_two_rows_in_the_table(index):
    context = _ask(index, NVDA_TWO_YEARS)

    q3 = next(r for r in context.financial_facts if r.fiscal_period == "Q3 FY2026")
    # 57,006 against 35,082 a year earlier.
    assert q3.year_on_year == pytest.approx(57_006 / 35_082 - 1)
    assert {_source(context, t).filing_id for t in q3.year_on_year_sources} == {
        "NVDA_10-Q_2025-10-26",
        "NVDA_10-Q_2024-10-27",
    }
    line = next(line for line in _facts_section(context).splitlines() if "| Q3 FY2026 (" in line)
    assert "+62.5%" in line


def test_the_annual_figures_of_the_window_are_in_the_table(index):
    context = _ask(index, NVDA_TWO_YEARS)

    years = {
        r.fiscal_period: r.value
        for r in context.financial_facts
        if r.metric == "revenue" and r.months == 12
    }
    assert years == {"FY2024": 60_922_000_000, "FY2025": 130_497_000_000}


@pytest.mark.parametrize(
    ("question", "metrics"),
    [
        ("How has NVIDIA's revenue changed over the last two years?", ("revenue",)),
        ("How have NVIDIA's sales grown over the last two years?", ("revenue",)),
        ("What drove NVIDIA's top line over the last two years?", ("revenue",)),
        ("How has NVIDIA's net income changed over the last two years?", ("net_income",)),
        ("Were NVIDIA's earnings up over the last two years?", ("net_income",)),
        ("Is NVIDIA's profit growing over the last two years?", ("net_income",)),
        (
            "How did NVIDIA's revenue and net income change over the last two years?",
            ("revenue", "net_income"),
        ),
    ],
)
def test_metric_words_fetch_that_metric_from_the_store(index, question, metrics):
    context = _ask(index, question)

    assert context.query_scope.metrics == metrics
    assert {r.metric for r in context.financial_facts} == set(metrics)


def test_a_segment_name_fetches_that_segments_revenue(index):
    context = _ask(
        index, "How has NVIDIA's Compute & Networking business grown over the last year?"
    )

    assert context.query_scope.segments == ("Compute & Networking",)
    rows = context.financial_facts
    assert rows and {(r.metric, r.segment) for r in rows} == {
        ("segment_revenue", "Compute & Networking")
    }
    q3 = next(r for r in rows if r.fiscal_period == "Q3 FY2026")
    assert q3.value == 50_908_000_000
    assert "Segment revenue: Compute & Networking" in _facts_section(context)


def test_a_one_word_segment_name_counts_only_when_capitalised(index):
    named = _ask(index, "How has NVIDIA's Graphics revenue changed over the last year?")
    word = _ask(index, "Are graphics cards a risk for NVIDIA?")

    assert named.query_scope.segments == ("Graphics",)
    assert word.query_scope.segments == ()
    assert word.financial_facts == ()


def test_segment_alone_fetches_every_segment(index):
    context = _ask(index, "How has NVIDIA's revenue by segment changed over the last year?")

    assert {r.segment for r in context.financial_facts if r.metric == "segment_revenue"} == {
        "Compute & Networking",
        "Graphics",
    }


def test_a_question_naming_no_metric_gets_no_financial_facts(index):
    context = _ask(index, "What are NVIDIA's main risk factors?")

    assert context.financial_facts == ()
    assert all(s.kind == "text" for s in context.sources)
    assert "# Financial Facts" not in _user_prompt(context)


# --- Segment reorganisations -----------------------------------------------------------


def test_a_segment_trend_stops_at_a_segment_reorganisation_and_says_so(segments_index):
    context = _ask(
        segments_index, "How has Disney's segment revenue changed over the last three years?"
    )

    rows = [r for r in context.financial_facts if r.metric == "segment_revenue"]
    assert {r.segment for r in rows} == {"Entertainment", "Sports", "Experiences"}
    # The new segments start with the FY2023 10-K; the 10-Qs before it are left out.
    assert min(r.report_period for r in rows) == "2023-09-30"
    (note,) = [n for n in context.fact_notes if n.kind == "segments_changed"]
    assert note.ticker == "DIS"
    assert "Q3 FY2023" in note.text and "FY2023" in note.text
    assert "Disney Media and Entertainment Distribution" in note.text
    assert note.text in _facts_section(context)


def test_a_segment_dropped_in_a_reorganisation_is_said_to_be_no_longer_reported(segments_index):
    context = _ask(
        segments_index,
        "How has Coca-Cola's Global Ventures revenue changed over the last two years?",
    )

    assert context.query_scope.segments == ("Global Ventures",)
    assert not [r for r in context.financial_facts if r.segment == "Global Ventures"]
    notes = {n.kind: n.text for n in context.fact_notes}
    assert "no longer reported: Global Ventures" in notes["segments_changed"]
    assert "read from the Filing text" in notes["text_fallback"]


def test_a_fourth_quarter_is_not_derived_across_a_segment_reorganisation(segments_index):
    context = _ask(
        segments_index, "How has Disney's segment revenue changed over the last three years?"
    )

    segment_periods = {
        r.fiscal_period for r in context.financial_facts if r.metric == "segment_revenue"
    }
    assert "Q4 FY2023" not in segment_periods
    assert "Q4 FY2024" in segment_periods


# --- Falling back to text --------------------------------------------------------------


def test_a_snapshot_company_falls_back_to_the_filing_text_and_the_answer_says_so(index):
    context = _ask(index, "How has JPMorgan's revenue changed over the last two years?")

    assert context.financial_facts == ()
    (note,) = context.fact_notes
    assert (note.kind, note.ticker, note.metric) == ("text_fallback", "JPM", "revenue")
    facts = _facts_section(context)
    assert note.text in facts
    assert "read from the Filing text" in note.text
    assert [s for s in context.sources if s.kind == "text"]  # the text is still retrieved
    assert "read it from a Source's text instead, say it was read from the Filing text" in (
        context.messages[0].content.replace("\n", " ")
    )


def test_a_company_whose_segments_were_not_extracted_falls_back_to_text(index):
    context = _ask(index, "How has Target's revenue by segment changed over the last year?")

    kinds = {(n.ticker, n.metric, n.kind) for n in context.fact_notes}
    assert ("TGT", "segment_revenue", "text_fallback") in kinds


def test_only_the_companies_the_store_can_answer_get_rows(index):
    context = _ask(index, "Compare the revenue of NVIDIA and JPMorgan over the last year.")

    assert {r.ticker for r in context.financial_facts} == {"NVDA"}
    assert {n.ticker for n in context.fact_notes} == {"JPM"}


def test_a_facts_sources_text_holds_the_figures_derived_from_it(index):
    """A citation of a derived figure leads to text that states it: the 10-K's Facts
    Source states its derived fourth quarter, and each Facts Source the year-on-year
    changes of its own rows."""
    context = _ask(index, NVDA_TWO_YEARS)
    by_filing = {s.filing_id: s for s in context.sources if s.kind == "facts"}

    annual = by_filing["NVDA_10-K_2025-01-26"].text
    assert "$130,497 million" in annual
    assert "Q4 FY2025" in annual and "$39,331 million" in annual and "derived" in annual
    assert "+114.2%" in annual
    assert "+62.5%" in by_filing["NVDA_10-Q_2025-10-26"].text
    # The 10-Qs a fourth quarter subtracts state only what they report.
    assert "derived" not in by_filing["NVDA_10-Q_2023-04-30"].text
