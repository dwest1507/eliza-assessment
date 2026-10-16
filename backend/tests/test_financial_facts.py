"""Tests through the Financial Facts seam.

Most use small flattened-table excerpts, written the way tables appear in a cleaned
Filing body, inside a real Filing whose body is replaced by the excerpt. A few check
real Corpus Filings against values read by hand from the Filing text.
"""

from dataclasses import replace
from datetime import date

import pytest

from edgar_rag.corpus import DEFAULT_CORPUS_DIR, load_filing
from edgar_rag.financial_facts import extract_financial_facts


@pytest.fixture(scope="module")
def annual():
    """Apple's FY2024 10-K (Report Period 2024-09-28), as a carrier for excerpts."""
    return load_filing(DEFAULT_CORPUS_DIR / "AAPL_10K_2024Q3_2024-11-01_full.txt")


@pytest.fixture(scope="module")
def quarterly():
    """Alphabet's Q3 2025 10-Q (Report Period 2025-09-30), as a carrier for excerpts."""
    return load_filing(DEFAULT_CORPUS_DIR / "GOOG_10Q_2025Q3_2025-10-30_full.txt")


def _revenue(filing, excerpt):
    facts = extract_financial_facts(replace(filing, body=excerpt, toc=None, sections=()))
    revenue = [f for f in facts if f.metric == "revenue"]
    assert len(revenue) <= 1
    return revenue[0] if revenue else None


def test_revenue_in_millions_is_returned_in_base_units(annual):
    excerpt = (
        "CONSOLIDATED STATEMENTS OF OPERATIONS(In millions, except per-share amounts)\n"
        "| Years ended\n"
        "| September 28,2024 |  | September 30,2023\n"
        "Revenue | $ | 46,743 |  |  | $ | 30,040 |\n"
        "Net income | $ | 1,001 |  |  | $ | 900 |\n"
    )

    fact = _revenue(annual, excerpt)

    assert fact.value == 46_743_000_000
    assert fact.unit == "USD"
    assert fact.ticker == "AAPL"
    assert fact.report_period == date(2024, 9, 28)
    assert fact.filing_id == "AAPL_10-K_2024-09-28"
    assert fact.period_months == 12
    assert fact.label == "Revenue"


def test_scale_word_on_its_own_header_row_in_thousands(annual):
    excerpt = (
        "Consolidated Statements of Income\n"
        "| (In thousands, except per share data)\n"
        "| 2024 |  | 2023\n"
        "Total revenues | $ | 1,234,567 |  |  | $ | 1,000,000 |\n"
        "Net income | $ | 12,345 |  |  | $ | 10,000 |\n"
    )

    assert _revenue(annual, excerpt).value == 1_234_567_000


def test_scale_written_as_millions_of_dollars_in_the_first_header_cell(quarterly):
    excerpt = (
        "CONDENSED CONSOLIDATED STATEMENT OF INCOME\n"
        "(millions of dollars, unless noted) | Three Months EndedSeptember 30, | Nine Months"
        " EndedSeptember 30,\n"
        "2025 | 2024 | 2025 | 2024\n"
        "Sales and other operating revenue | 79,477 |  | 89,986 |  | 160,535 |  | 170,397 |\n"
        "Total revenues and other income | 81,506 |  | 93,060 |  | 164,636 |  | 176,143 |\n"
        "Net income | 7,082 |  | 9,240 |  | 14,795 |  | 17,460 |\n"
    )

    fact = _revenue(quarterly, excerpt)

    assert fact.value == 81_506_000_000
    assert fact.label == "Total revenues and other income"


def test_negative_values_in_parentheses(annual):
    excerpt = (
        "STATEMENTS OF OPERATIONS (in millions)\n"
        "| 2024 |  | 2023\n"
        "Revenues | $ | (1,250) |  |  | $ | 310 |\n"
        "Net income (loss) | $ | (4,400) |  |  | $ | (2,000) |\n"
    )

    assert _revenue(annual, excerpt).value == -1_250_000_000


def test_revenue_that_is_not_the_first_row_is_found_and_its_total_wins_over_its_parts(annual):
    excerpt = (
        "CONSOLIDATED STATEMENTS OF OPERATIONS(In millions)\n"
        "| Years ended\n"
        "| September 28,2024 |  | September 30,2023 |  | September 24,2022\n"
        "Net sales: |  |  |  |  |\n"
        "Products | $ | 294,866 |  |  | $ | 298,085 |  |  | $ | 316,199 |\n"
        "Services | 96,169 |  |  | 85,200 |  |  | 78,129 |\n"
        "Total net sales | 391,035 |  |  | 383,285 |  |  | 394,328 |\n"
        "Cost of sales: |  |  |  |  |\n"
        "Net income | $ | 93,736 |  |  | $ | 96,995 |  |  | $ | 99,803 |\n"
    )

    fact = _revenue(annual, excerpt)

    assert fact.value == 391_035_000_000
    assert fact.label == "Total net sales"


def test_column_is_chosen_by_header_year_when_the_prior_year_comes_first(quarterly):
    excerpt = (
        "CONSOLIDATED STATEMENTS OF INCOME(in millions, except per share amounts)\n"
        "| Three Months Ended |  | Nine Months Ended\n"
        "| September 30, |  | September 30,\n"
        "| 2024 |  | 2025 |  | 2024 |  | 2025\n"
        "Revenues | $ | 88,268 |  |  | $ | 102,346 |  |  | $ | 253,549 |  |  | $ | 289,007 |\n"
        "Cost of revenues | 36,474 |  |  | 41,369 |  |  | 105,693 |  |  | 116,768 |\n"
        "Net income | $ | 26,301 |  |  | $ | 34,979 |  |  | $ | 70,603 |  |  | $ | 97,190 |\n"
    )

    fact = _revenue(quarterly, excerpt)

    assert fact.value == 102_346_000_000
    assert fact.period_months == 3


def test_percentage_change_columns_are_skipped(annual):
    excerpt = (
        "The following table shows net sales for 2024, 2023 and 2022 (dollars in millions):\n"
        "| 2024 |  | Change |  | 2023 |  | Change |  | 2022\n"
        "Total net sales | $ | 391,035 |  |  | 2 | % |  | $ | 383,285 |  |  | (3) | % |"
        "  | $ | 394,328 |\n"
    )

    assert _revenue(annual, excerpt).value == 391_035_000_000


def test_income_statement_is_preferred_over_an_earlier_revenue_table(annual):
    excerpt = (
        "Segment net sales (in millions)\n"
        "| 2024 |  | 2023\n"
        "Americas | $ | 167,045 |  |  | $ | 162,560 |\n"
        "Net sales | $ | 167,045 |  |  | $ | 162,560 |\n"
        "Some prose between the tables.\n"
        "CONSOLIDATED STATEMENTS OF OPERATIONS (In millions)\n"
        "| 2024 |  | 2023\n"
        "Total net sales | $ | 391,035 |  |  | $ | 383,285 |\n"
        "Net income | $ | 93,736 |  |  | $ | 96,995 |\n"
    )

    assert _revenue(annual, excerpt).value == 391_035_000_000


def test_titled_income_statement_is_preferred_over_an_earlier_summary_table(annual):
    # ExxonMobil's 10-K summary table has a net income row but shows only part of revenue.
    excerpt = (
        "FINANCIAL INFORMATION\n"
        "(millions of dollars, except where stated otherwise) |  | 2024 |  | 2023\n"
        "Sales and other operating revenue |  |  | 339,247 |  |  | 334,697 |\n"
        "Net income (loss) attributable to ExxonMobil |  |  | 33,680 |  |  | 36,010 |\n"
        "Some prose between the tables.\n"
        "CONSOLIDATED STATEMENT OF INCOME\n"
        "(millions of dollars) | NoteReferenceNumber |  | 2024 |  | 2023\n"
        "Sales and other operating revenue | 18 |  | 339,247 |  |  | 334,697 |\n"
        "Total revenues and other income |  |  | 349,585 |  |  | 344,582 |\n"
        "Net income including noncontrolling interests |  |  | 35,056 |  |  | 37,354 |\n"
    )

    fact = _revenue(annual, excerpt)

    assert fact.value == 349_585_000_000
    assert fact.label == "Total revenues and other income"


def test_no_fact_rather_than_a_guess_when_the_scale_or_period_is_unknown(annual):
    no_scale = (
        "STATEMENTS OF OPERATIONS\n"
        "| 2024 |  | 2023\n"
        "Revenues | 100 |  | 90 |\n"
        "Net income | 1 |  | 1 |\n"
    )
    no_year = (
        "STATEMENTS OF OPERATIONS (in millions)\n"
        "| 2019 |  | 2018\n"
        "Revenues | 100 |  | 90 |\n"
        "Net income | 1 |  | 1 |\n"
    )

    assert _revenue(annual, no_scale) is None
    assert _revenue(annual, no_year) is None


@pytest.mark.parametrize(
    "name, period_months, value",
    [
        # Values read by hand from each Filing's income statement.
        ("AAPL_10K_2024Q3_2024-11-01_full.txt", 12, 391_035_000_000),
        ("GOOG_10Q_2025Q3_2025-10-30_full.txt", 3, 102_346_000_000),
        ("XOM_10Q_2025Q2_2025-08-04_full.txt", 3, 81_506_000_000),
    ],
)
def test_revenue_of_real_tracked_company_filings(name, period_months, value):
    facts = extract_financial_facts(load_filing(DEFAULT_CORPUS_DIR / name))

    assert [(f.metric, f.period_months, f.value) for f in facts] == [
        ("revenue", period_months, value)
    ]
