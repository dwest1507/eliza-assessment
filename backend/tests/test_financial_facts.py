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


def _facts(filing, excerpt, metric):
    facts = extract_financial_facts(replace(filing, body=excerpt, toc=None, sections=()))
    return [f for f in facts if f.metric == metric]


def _revenue(filing, excerpt):
    revenue = _facts(filing, excerpt, "revenue")
    assert len(revenue) <= 1
    return revenue[0] if revenue else None


def _net_income(filing, excerpt):
    net_income = _facts(filing, excerpt, "net_income")
    assert len(net_income) <= 1
    return net_income[0] if net_income else None


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


def test_net_income_is_read_from_the_income_statement_in_base_units(annual):
    excerpt = (
        "CONSOLIDATED STATEMENTS OF OPERATIONS(In millions, except per-share amounts)\n"
        "| Years ended\n"
        "| September 28,2024 |  | September 30,2023\n"
        "Total net sales | 391,035 |  |  | 383,285 |\n"
        "Provision for income taxes | 29,749 |  |  | 16,741 |\n"
        "Net income | $ | 93,736 |  |  | $ | 96,995 |\n"
    )

    fact = _net_income(annual, excerpt)

    assert fact.value == 93_736_000_000
    assert fact.unit == "USD"
    assert fact.label == "Net income"
    assert fact.period_months == 12
    assert fact.filing_id == "AAPL_10-K_2024-09-28"


def test_net_income_attributable_to_the_company_wins_over_the_consolidated_total(quarterly):
    excerpt = (
        "CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS (in millions)\n"
        "| Three Months Ended September 30, |  | Nine Months Ended September 30,\n"
        "| 2025 |  | 2024 |  | 2025 |  | 2024\n"
        "Total revenues | $ | 28,095 |  |  | $ | 25,182 |  |  | $ | 69,926 |  |  | $ | 71,983 |\n"
        "Net income including noncontrolling interests | 1,423 |  |  | 2,183 |  |  | 3,061 |  |"
        "  | 4,700 |\n"
        "Less: Net income attributable to noncontrolling interests | 50 |  |  | 16 |  |  | 82 |  |"
        "  | 54 |\n"
        "Net income attributable to common stockholders | $ | 1,373 |  |  | $ | 2,167 |  |  | $ |"
        " 2,979 |  |  | $ | 4,646 |\n"
    )

    fact = _net_income(quarterly, excerpt)

    assert fact.value == 1_373_000_000
    assert fact.label == "Net income attributable to common stockholders"
    assert fact.period_months == 3


def test_a_net_loss_in_parentheses_is_negative(annual):
    excerpt = (
        "STATEMENTS OF OPERATIONS (in thousands)\n"
        "| 2024 |  | 2023\n"
        "Revenues | $ | 120,500 |  |  | $ | 98,000 |\n"
        "Net income (loss) | $ | (4,400) |  |  | $ | 2,000 |\n"
    )

    assert _net_income(annual, excerpt).value == -4_400_000


def test_a_net_loss_written_after_the_dollar_sign_and_labelled_loss_first(quarterly):
    # UnitedHealth's "Net (loss) earnings"; J&J's "$(68)" with the sign inside.
    excerpt = (
        "Condensed Consolidated Statements of Operations\n"
        "|  | Three Months EndedSeptember 30,\n"
        "(in millions, except per share data) |  | 2025 |  | 2024\n"
        "Total revenues |  | $102,346 |  | $88,268 |\n"
        "Net (loss) earnings |  | $(1,221) |  |  |  |  | $5,774 |  |\n"
    )

    assert _net_income(quarterly, excerpt).value == -1_221_000_000


def test_per_share_values_are_neither_net_income_nor_scaled_to_millions(quarterly):
    # "In millions, except per share amounts": the per-share rows sit under the scale
    # word but are dollars per share. Neither may become a net income of $2.31 million.
    excerpt = (
        "CONSOLIDATED STATEMENTS OF INCOME(in millions, except per share amounts)\n"
        "| Three Months Ended |  | Nine Months Ended\n"
        "| 2025 |  | 2024 |  | 2025 |  | 2024\n"
        "Revenues | $ | 102,346 |  |  | $ | 88,268 |  |  | $ | 289,007 |  |  | $ | 253,549 |\n"
        "Net income per share: |  |  |  |  |  |  |\n"
        "Net income per share - basic | 2.89 |  |  | 2.14 |  |  | 7.92 |  |  | 5.82 |\n"
        "Net income per share - diluted | 2.87 |  |  | 2.12 |  |  | 7.85 |  |  | 5.77 |\n"
        "Net income | $ | 34,979 |  |  | $ | 26,301 |  |  | $ | 97,715 |  |  | $ | 73,582 |\n"
    )
    per_share_only = excerpt.rsplit("Net income |", 1)[0]

    assert _net_income(quarterly, excerpt).value == 34_979_000_000
    assert _net_income(quarterly, per_share_only) is None


_INCOME_STATEMENT = (
    "CONSOLIDATED STATEMENTS OF INCOME(in millions, except per share amounts)\n"
    "| Three Months Ended |  | Nine Months Ended\n"
    "| 2025 |  | 2024 |  | 2025 |  | 2024\n"
    "Revenues | $ | 102,346 |  |  | $ | 88,268 |  |  | $ | 289,007 |  |  | $ | 253,549 |\n"
    "Net income | $ | 34,979 |  |  | $ | 26,301 |  |  | $ | 97,715 |  |  | $ | 73,582 |\n"
    "Prose between the statements and the notes.\n"
)


def _segments(filing, excerpt):
    return {f.segment: f.value for f in _facts(filing, excerpt, "segment_revenue")}


def test_segment_rows_above_a_total_that_reconciles_to_revenue(quarterly):
    excerpt = _INCOME_STATEMENT + (
        "The following table presents revenue and operating income by segment (in millions):\n"
        "| Three Months Ended |  | Nine Months Ended\n"
        "| 2025 |  | 2024 |  | 2025 |  | 2024\n"
        "Revenues: |  |  |  |  |  |  |\n"
        "Google Services | 87,052 |  |  | 76,510 |  |  | 246,859 |  |  | 220,836 |\n"
        "Google Cloud | 15,157 |  |  | 11,353 |  |  | 41,041 |  |  | 31,274 |\n"
        "Other Bets (1) | 344 |  |  | 388 |  |  | 1,167 |  |  | 1,248 |\n"
        "Hedging gains (losses) | (207) |  |  | 17 |  |  | (60) |  |  | 191 |\n"
        "Total revenues | 102,346 |  |  | 88,268 |  |  | 289,007 |  |  | 253,549 |\n"
        "Operating income (loss): |  |  |  |  |  |  |\n"
        "Google Services | $ | 33,527 |  |  | $ | 30,856 |  |  | $ | 97,005 |  |  | $ | 85,370 |\n"
    )

    facts = _facts(quarterly, excerpt, "segment_revenue")

    # Hedging gains reconcile the segments to revenue but are not a segment.
    assert {f.segment: f.value for f in facts} == {
        "Google Services": 87_052_000_000,
        "Google Cloud": 15_157_000_000,
        "Other Bets": 344_000_000,
    }
    assert {f.period_months for f in facts} == {3}
    assert {f.unit for f in facts} == {"USD"}


def test_a_subtotal_of_segments_is_one_segment_not_added_twice(quarterly):
    # UnitedHealth's layout: Optum subtotals its three businesses and their eliminations.
    excerpt = _INCOME_STATEMENT + (
        "The following table presents a summary of the reportable segment financial"
        " information:\n"
        "|  | Three Months Ended September 30,\n"
        "(in millions) |  | 2025 |  | 2024\n"
        "Revenues |  |  |  |\n"
        "UnitedHealthcare |  | $ | 60,000 |  |  | $ | 50,000 |\n"
        "Optum Health |  | 25,000 |  |  | 22,000 |\n"
        "Optum Rx |  | 38,000 |  |  | 33,000 |\n"
        "Optum eliminations |  | (654) |  |  | (500) |\n"
        "Optum |  | 62,346 |  |  | 54,500 |\n"
        "Eliminations |  | (20,000) |  |  | (16,232) |\n"
        "Consolidated revenues |  | $ | 102,346 |  |  | $ | 88,268 |\n"
    )

    assert _segments(quarterly, excerpt) == {
        "UnitedHealthcare": 60_000_000_000,
        "Optum": 62_346_000_000,
    }


def test_a_row_with_a_dash_for_the_period_does_not_end_the_segment_rows(annual):
    # Disney's MD&A layout: a reconciling row that is nil this year.
    excerpt = (
        "CONSOLIDATED STATEMENTS OF INCOME (in millions)\n"
        "| 2024 |  | 2023\n"
        "Total revenues | 88,898 |  |  | 82,722 |\n"
        "Net income | 2,354 |  |  | 3,145 |\n"
        "The following table presents revenues by segment:\n"
        "($ in millions) | 2024 |  | 2023 |  | % ChangeBetter (Worse)\n"
        "Entertainment | $ | 40,635 |  |  | $ | 39,569 |  |  | 3  %\n"
        "Sports | 17,111 |  |  | 17,270 |  |  | (1) %\n"
        "Experiences | 32,549 |  |  | 28,085 |  |  | 16  %\n"
        "Eliminations | (1,397) |  |  | (1,179) |  |  | (18) %\n"
        "Content License Early Termination | — |  |  | (1,023) |  |  | 100  %\n"
        "Revenues | $ | 88,898 |  |  | $ | 82,722 |  |  | 7  %\n"
    )

    assert _segments(annual, excerpt) == {
        "Entertainment": 40_635_000_000,
        "Sports": 17_111_000_000,
        "Experiences": 32_549_000_000,
    }


def test_segments_as_headings_each_with_its_own_revenue_row(annual):
    # Amazon's layout: a heading per segment, then its net sales and operating income.
    excerpt = (
        "CONSOLIDATED STATEMENTS OF OPERATIONS (in millions)\n"
        "| 2024 |  | 2023\n"
        "Total net sales | 637,959 |  |  | 574,785 |\n"
        "Net income | 59,248 |  |  | 30,425 |\n"
        "Information on reportable segments and reconciliation to consolidated net income is"
        " as follows (in millions):\n"
        "| Year Ended December 31,\n"
        "| 2023 |  | 2024\n"
        "North America |  |  |  |\n"
        "Net sales | $ | 352,828 |  |  | $ | 387,497 |\n"
        "Operating income | $ | 14,877 |  |  | $ | 24,967 |\n"
        "International |  |  |  |\n"
        "Net sales | $ | 131,200 |  |  | $ | 142,906 |\n"
        "Operating income (loss) | $ | (2,656) |  |  | $ | 3,792 |\n"
        "AWS |  |  |  |\n"
        "Net sales | $ | 90,757 |  |  | $ | 107,556 |\n"
        "Operating income | $ | 24,631 |  |  | $ | 39,834 |\n"
        "Consolidated |  |  |  |\n"
        "Net sales | $ | 574,785 |  |  | $ | 637,959 |\n"
    )

    facts = _facts(annual, excerpt, "segment_revenue")

    assert {f.segment: f.value for f in facts} == {
        "North America": 387_497_000_000,
        "International": 142_906_000_000,
        "AWS": 107_556_000_000,
    }
    assert {(f.label, f.period_months) for f in facts} == {("Net sales", 12)}


def test_no_segment_revenue_when_the_segments_do_not_add_up_to_revenue(quarterly):
    excerpt = _INCOME_STATEMENT + (
        "Revenue by reportable segment (in millions):\n"
        "| 2025 |  | 2024\n"
        "Americas | $ | 50,000 |  |  | $ | 40,000 |\n"
        "Europe | 40,000 |  |  | 30,000 |\n"
        "Total net sales | $ | 102,346 |  |  | $ | 88,268 |\n"
    )

    assert _segments(quarterly, excerpt) == {}


@pytest.mark.parametrize(
    "name, period_months, revenue, net_income",
    [
        # Values read by hand from each Filing's income statement.
        ("AAPL_10K_2024Q3_2024-11-01_full.txt", 12, 391_035_000_000, 93_736_000_000),
        ("GOOG_10Q_2025Q3_2025-10-30_full.txt", 3, 102_346_000_000, 34_979_000_000),
        # ExxonMobil's: net income attributable to ExxonMobil, not including NCI.
        ("XOM_10Q_2025Q2_2025-08-04_full.txt", 3, 81_506_000_000, 7_082_000_000),
    ],
)
def test_revenue_and_net_income_of_real_tracked_company_filings(
    name, period_months, revenue, net_income
):
    facts = extract_financial_facts(load_filing(DEFAULT_CORPUS_DIR / name))
    by_metric = {f.metric: f for f in facts if f.metric in ("revenue", "net_income")}

    assert {m: (f.period_months, f.value) for m, f in by_metric.items()} == {
        "revenue": (period_months, revenue),
        "net_income": (period_months, net_income),
    }


@pytest.mark.parametrize(
    "name, segments",
    [
        # Values read by hand from each Filing's segment note.
        (
            "MSFT_10Q_2025Q1_2025-04-30_full.txt",
            {
                "Productivity and Business Processes": 29_944_000_000,
                "Intelligent Cloud": 26_751_000_000,
                "More Personal Computing": 13_371_000_000,
            },
        ),
        (
            "AMZN_10Q_2025Q2_2025-08-01_full.txt",
            {
                "North America": 100_068_000_000,
                "International": 36_761_000_000,
                "AWS": 30_873_000_000,
            },
        ),
        # Segments as columns.
        (
            "KO_10Q_2025Q2_2025-07-24_full.txt",
            {
                "Europe, Middle East & Africa": 3_176_000_000,
                "Latin America": 1_587_000_000,
                "North America": 5_029_000_000,
                "Asia Pacific": 1_572_000_000,
                "Bottling Investments": 1_411_000_000,
            },
        ),
        (
            "NVDA_10K_2025-02-26_full.txt",
            {"Compute & Networking": 116_193_000_000, "Graphics": 14_304_000_000},
        ),
        # Each segment's U.S. and non-U.S. columns added: Upstream is 12,267 + 13,433.
        (
            "XOM_10Q_2025Q2_2025-08-04_full.txt",
            {
                "Upstream": 25_700_000_000,
                "Energy Products": 71_147_000_000,
                "Chemical Products": 8_298_000_000,
                "Specialty Products": 5_262_000_000,
            },
        ),
    ],
)
def test_segment_revenue_of_real_tracked_company_filings(name, segments):
    facts = extract_financial_facts(load_filing(DEFAULT_CORPUS_DIR / name))

    assert {f.segment: f.value for f in facts if f.metric == "segment_revenue"} == segments


# Segment tables laid out in columns: one column per segment, one block of rows per
# period, each block headed by a row naming its period.

_KO_INCOME_STATEMENT = (
    "CONDENSED CONSOLIDATED STATEMENTS OF INCOME (In millions)\n"
    "| Three Months Ended |  | Six Months Ended\n"
    "| June 27,2025 | June 28,2024 |  | June 27,2025 | June 28,2024\n"
    "Net Operating Revenues | $ | 12,535 |  | $ | 12,363 |  |  | $ | 23,664 |  | $ | 23,663 |\n"
    "Net income | $ | 3,810 |  | $ | 2,411 |  |  | $ | 7,140 |  | $ | 5,588 |\n"
    "Prose between the statements and the notes.\n"
)


@pytest.fixture(scope="module")
def ko_quarterly():
    """Coca-Cola's Q2 2025 10-Q (Report Period 2025-06-27), as a carrier for excerpts."""
    return load_filing(DEFAULT_CORPUS_DIR / "KO_10Q_2025Q2_2025-07-24_full.txt")


def test_segments_as_columns_with_a_block_of_rows_per_period(ko_quarterly):
    # Coca-Cola's layout: Corporate and Eliminations reconcile the segments to the
    # Consolidated column, which equals revenue. None of the three is a segment.
    excerpt = _KO_INCOME_STATEMENT + (
        "NOTE 17: OPERATING SEGMENTS Information about our Company's operations by operating"
        " segment and Corporate is as follows (in millions):\n"
        "| Europe, Middle East & Africa | LatinAmerica | NorthAmerica | Corporate |"
        " Eliminations | Consolidated\n"
        "Three Months Ended June 27, 2025 |  |  |  |  |  |\n"
        "Net operating revenues: |  |  |  |  |  |\n"
        "Third party | $ | 3,008 |  | $ | 1,587 |  | $ | 7,901 |  | $ | 39 |  | $ | — |  |"
        " $ | 12,535 |\n"
        "Intersegment | 168 |  | — |  | 111 |  | — |  | (279) |  | — |\n"
        "Total net operating revenues | 3,176 |  | 1,587 |  | 8,012 |  | 39 |  | (279) |  |"
        " 12,535 |\n"
        "Operating income (loss) | 1,000 |  | 900 |  | 2,000 |  | (300) |  | — |  | 3,600 |\n"
        "Three Months Ended June 28, 2024 |  |  |  |  |  |\n"
        "Net operating revenues: |  |  |  |  |  |\n"
        "Total net operating revenues | 3,028 |  | 1,652 |  | 7,970 |  | 35 |  | (322) |  |"
        " 12,363 |\n"
    )

    facts = _facts(ko_quarterly, excerpt, "segment_revenue")

    # Header cells flattened from wrapped lines ("LatinAmerica") get their space back.
    assert {f.segment: f.value for f in facts} == {
        "Europe, Middle East & Africa": 3_176_000_000,
        "Latin America": 1_587_000_000,
        "North America": 8_012_000_000,
    }
    assert {(f.label, f.period_months, f.unit) for f in facts} == {
        ("Total net operating revenues", 3, "USD")
    }


def test_the_period_block_is_chosen_by_its_heading_not_its_position(annual):
    # NVIDIA's layout, with the prior year's block first: the 2024 block must be read.
    excerpt = (
        "CONSOLIDATED STATEMENTS OF INCOME (In millions)\n"
        "| 2024 |  | 2023\n"
        "Revenue | $ | 130,497 |  |  | $ | 60,922 |\n"
        "Net income | $ | 72,880 |  |  | $ | 29,760 |\n"
        "The table below presents details of our reportable segments.\n"
        "| Compute & Networking |  | Graphics |  | All Other |  | Consolidated\n"
        "| (In millions)\n"
        "Year Ended Sep 30, 2023 |  |  |  |  |  |  |\n"
        "Revenue | $ | 47,405 |  |  | $ | 13,517 |  |  | $ | — |  |  | $ | 60,922 |\n"
        "Year Ended Sep 28, 2024 |  |  |  |  |  |  |\n"
        "Revenue | $ | 116,193 |  |  | $ | 14,304 |  |  | $ | — |  |  | $ | 130,497 |\n"
        "Operating income (loss) | $ | 82,875 |  |  | $ | 5,085 |  |  | $ | (6,507) |  |  |"
        " $ | 81,453 |\n"
    )

    # "All Other" has a dash for revenue: nil, not a segment with revenue of zero.
    assert _segments(annual, excerpt) == {
        "Compute & Networking": 116_193_000_000,
        "Graphics": 14_304_000_000,
    }


def test_no_segment_revenue_when_the_segment_columns_do_not_add_up_to_revenue(ko_quarterly):
    excerpt = _KO_INCOME_STATEMENT + (
        "Information about our Company's operations by operating segment is as follows"
        " (in millions):\n"
        "| North America | Asia Pacific | Consolidated\n"
        "Three Months Ended June 27, 2025 |  |  |\n"
        "Total net operating revenues | 5,000 |  | 1,500 |  | 6,500 |\n"
    )

    assert _segments(ko_quarterly, excerpt) == {}


def test_no_segment_revenue_from_columns_not_introduced_as_segments(ko_quarterly):
    # Columns that add up to revenue but are not called segments: sales channels, say.
    excerpt = _KO_INCOME_STATEMENT + (
        "Net operating revenues by channel are as follows (in millions):\n"
        "| Concentrate | Finished goods | Consolidated\n"
        "Three Months Ended June 27, 2025 |  |  |\n"
        "Total net operating revenues | 7,000 |  | 5,535 |  | 12,535 |\n"
    )

    assert _segments(ko_quarterly, excerpt) == {}


def test_segments_split_into_sub_columns_and_reconciled_to_revenue_below(quarterly):
    # ExxonMobil's layout: each segment split U.S. / non-U.S., a Segment Total column
    # that includes intersegment revenue, and a reconciliation of that total to revenue
    # further down the table. A segment's revenue is the sum of its two columns.
    excerpt = (
        "CONDENSED CONSOLIDATED STATEMENT OF INCOME\n"
        "(millions of dollars) | Three Months EndedSeptember 30, | Nine Months Ended"
        "September 30,\n"
        "2025 | 2024 | 2025 | 2024\n"
        "Total revenues and other income | 81,506 |  | 93,060 |  | 164,636 |  | 176,143 |\n"
        "Net income attributable to ExxonMobil | 7,082 |  | 9,240 |  | 14,795 |  | 17,460 |\n"
        "Note 8. Disclosures about Segments and Related Information\n"
        "(millions of dollars) | Upstream | Energy Products | Segment Total\n"
        "U.S. | Non-U.S. | U.S. | Non-U.S.\n"
        "Three Months Ended September 30, 2025 |  |  |  |  |\n"
        "Revenues and other income |  |  |  |  |\n"
        "Sales and other operating revenue | 5,939 |  | 3,286 |  | 25,072 |  | 34,917 |  |"
        " 69,214 |\n"
        "Intersegment revenue | 6,230 |  | 8,824 |  | 4,502 |  | 6,512 |  | 26,068 |\n"
        "Segment revenues and other income | 12,169 |  | 12,110 |  | 29,574 |  | 41,429 |  |"
        " 95,282 |\n"
        "Segment income (loss) | 1,212 |  | 4,190 |  | 825 |  | 541 |  | 6,768 |\n"
        "Reconciliation of consolidated revenues |  |  |  |  |\n"
        "Segment revenues and other income | 95,282 |  |  |  |\n"
        "Other revenues(2) | 12,292 |  |  |  |\n"
        "Elimination of intersegment revenues | (26,068) |  |  |  |\n"
        "Total consolidated revenues and other income | 81,506 |  |  |  |\n"
    )

    facts = _facts(quarterly, excerpt, "segment_revenue")

    assert {f.segment: f.value for f in facts} == {
        "Upstream": 24_279_000_000,
        "Energy Products": 71_003_000_000,
    }
    assert {f.label for f in facts} == {"Segment revenues and other income"}


def test_no_segment_revenue_when_the_reconciliation_below_does_not_reach_revenue(quarterly):
    excerpt = (
        "CONDENSED CONSOLIDATED STATEMENT OF INCOME\n"
        "(millions of dollars) | Three Months EndedSeptember 30,\n"
        "2025 | 2024\n"
        "Total revenues and other income | 81,506 |  | 93,060 |\n"
        "Net income attributable to ExxonMobil | 7,082 |  | 9,240 |\n"
        "Note 8. Disclosures about Segments and Related Information\n"
        "(millions of dollars) | Upstream | Energy Products | Segment Total\n"
        "Three Months Ended September 30, 2025 |  |  |  |\n"
        "Segment revenues and other income | 24,279 |  | 71,003 |  | 95,282 |\n"
        "Reconciliation of consolidated revenues |  |  |\n"
        "Segment revenues and other income | 95,282 |  |  |\n"
        "Elimination of intersegment revenues | (26,068) |  |  |\n"
        "Total consolidated revenues and other income | 81,506 |  |  |\n"
    )

    assert _segments(quarterly, excerpt) == {}
