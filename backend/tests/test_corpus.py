"""Tests through the Corpus seam, using real Corpus files as fixtures."""

import re
import shutil
from collections import Counter
from datetime import date, timedelta

import pytest

from edgar_rag.corpus import (
    DEFAULT_CORPUS_DIR,
    UNSECTIONED,
    check_manifest,
    load_corpus,
    load_filing,
    load_sector_table,
)


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


def _report_period_diagnostics(filing):
    return [d for d in filing.diagnostics if d.code.startswith("report_period")]


def _only(filings, **attrs):
    matches = [f for f in filings if all(getattr(f, k) == v for k, v in attrs.items())]
    assert len(matches) == 1, f"expected one Filing matching {attrs}, got {len(matches)}"
    return matches[0]


def test_filing_with_full_header_has_all_header_metadata():
    filing = load_filing(DEFAULT_CORPUS_DIR / "AAPL_10K_2024Q3_2024-11-01_full.txt")

    assert filing.company == "Apple Inc"
    assert filing.ticker == "AAPL"
    assert filing.cik == "0000320193"
    assert filing.form_type == "10-K"
    assert filing.filing_date == date(2024, 11, 1)
    assert filing.report_period == date(2024, 9, 28)
    assert filing.report_period_source == "header"
    assert filing.calendar_quarter == "2024Q3"
    assert filing.source_url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    )
    assert filing.diagnostics == ()


def test_filing_without_report_period_in_header_takes_it_from_the_url_cross_checked_by_text():
    filing = load_filing(DEFAULT_CORPUS_DIR / "AAPL_10K_2025-10-31_full.txt")

    assert filing.ticker == "AAPL"
    assert filing.form_type == "10-K"
    assert filing.filing_date == date(2025, 10, 31)
    assert filing.calendar_quarter is None
    assert filing.report_period == date(2025, 9, 27)
    assert filing.report_period_source == "url"
    assert filing.diagnostics == ()


def test_filing_whose_url_has_no_date_takes_its_report_period_from_the_text():
    filing = load_filing(DEFAULT_CORPUS_DIR / "GE_10K_2015-02-27_full.txt")

    assert filing.source_url.endswith("/gecc10k2014.htm")
    assert filing.report_period == date(2014, 12, 31)
    assert filing.report_period_source == "text"


def test_10q_takes_its_text_date_from_the_quarterly_period_sentence_not_a_10k_reference():
    # JPM's cover page puts "Commission file" between the phrase and the date, and the
    # body mentions "the year ended December 31, 2024" (its 10-K) earlier in the text.
    filing = load_filing(DEFAULT_CORPUS_DIR / "JPM_10Q_2025Q1_2025-05-01_full.txt")

    assert filing.report_period == date(2025, 3, 31)
    assert _report_period_diagnostics(filing) == []


@pytest.mark.parametrize(
    "name",
    ["T_10K_2026-02-09_full.txt", "MSFT_10Q_2024Q3_2024-10-30_full.txt"],
)
def test_period_sentence_is_found_when_the_date_runs_into_the_phrase(name):
    # Flattening glued the date to the phrase: "endedDecember 31, 2025",
    # "EndedSeptember 30,2024".
    filing = load_filing(DEFAULT_CORPUS_DIR / name)

    assert filing.diagnostics == ()


def test_url_and_text_disagreement_is_reported_as_a_diagnostic(tmp_path):
    # No real Filing disagrees, so a synthetic one isolates the case.
    path = tmp_path / "XYZ_10K_2025-02-01_full.txt"
    path.write_text(
        "Company: Example Corp\nTicker: XYZ\nFiling Type: 10-K (Annual Report)\n"
        "Filing Date: 2025-02-01\nCIK: 0000000001\nSource: SEC EDGAR\n"
        "URL: https://www.sec.gov/Archives/edgar/data/1/0001/xyz-20241231.htm\n"
        + "=" * 60
        + "\n\nFORM 10-KFor the fiscal year ended September 30, 2024\n",
        encoding="utf-8",
    )

    filing = load_filing(path)

    assert filing.report_period == date(2024, 12, 31)
    assert filing.report_period_source == "url"
    [mismatch] = _report_period_diagnostics(filing)
    assert mismatch.code == "report_period_mismatch"
    assert "url=2024-12-31" in mismatch.detail
    assert "text=2024-09-30" in mismatch.detail


def test_coca_cola_filings_sharing_a_calendar_quarter_have_distinct_identifiers(corpus):
    clash = [f for f in corpus if f.ticker == "KO" and f.calendar_quarter == "2022Q3"]

    assert len(clash) == 2
    assert {f.filing_id for f in clash} == {"KO_10-Q_2022-07-01", "KO_10-Q_2022-09-30"}
    # Coca-Cola's second fiscal quarter of 2022 ended on 1 July.
    assert {f.fiscal_period for f in clash} == {"Q2 FY2022", "Q3 FY2022"}


def test_fiscal_period_for_a_non_december_fiscal_year(corpus):
    nvda_july_2025 = _only(corpus, ticker="NVDA", report_period=date(2025, 7, 27))
    nvda_10k = _only(corpus, ticker="NVDA", report_period=date(2025, 1, 26))
    apple_q1 = _only(corpus, ticker="AAPL", report_period=date(2024, 12, 28))

    assert nvda_july_2025.form_type == "10-Q"
    assert nvda_july_2025.fiscal_year_end_month == 1
    assert nvda_july_2025.fiscal_period == "Q2 FY2026"
    assert nvda_10k.fiscal_period == "FY2025"
    assert apple_q1.fiscal_year_end_month == 9
    assert apple_q1.fiscal_period == "Q1 FY2025"


def test_load_corpus_returns_every_filing_in_the_manifest(corpus):
    assert len(corpus) == 246
    assert len({f.ticker for f in corpus}) == 54
    form_types = [f.form_type for f in corpus]
    assert form_types.count("10-K") == 89
    assert form_types.count("10-Q") == 157


def test_every_filing_has_a_report_period_its_source_and_a_unique_identifier(corpus):
    assert all(f.report_period is not None for f in corpus)
    assert {f.report_period_source for f in corpus} <= {"header", "url", "text"}
    assert len({f.filing_id for f in corpus}) == len(corpus)


def test_every_filing_has_a_fiscal_period(corpus):
    assert [f.filing_id for f in corpus if f.fiscal_period is None] == []


def test_manifest_matches_the_files_on_disk():
    assert check_manifest() == []


def test_manifest_check_reports_missing_and_extra_files(tmp_path):
    for name in ["manifest.json", "AAPL_10K_2025-10-31_full.txt"]:
        shutil.copy(DEFAULT_CORPUS_DIR / name, tmp_path / name)
    (tmp_path / "EXTRA_10K_2025-01-01_full.txt").write_text("", encoding="utf-8")

    problems = check_manifest(tmp_path)

    assert "extra on disk: EXTRA_10K_2025-01-01_full.txt" in problems
    assert "missing on disk: AAPL_10K_2022Q3_2022-10-28_full.txt" in problems
    assert "missing on disk: AAPL_10K_2025-10-31_full.txt" not in problems
    assert len(problems) == 1 + 245


# --- Body cleaning: XBRL noise and table of contents ---------------------------

APPLE_10K = DEFAULT_CORPUS_DIR / "AAPL_10K_2024Q3_2024-11-01_full.txt"


def test_cleaned_body_starts_at_the_cover_page_without_xbrl_noise():
    filing = load_filing(APPLE_10K)

    assert filing.body.startswith("UNITED STATESSECURITIES AND EXCHANGE COMMISSION")
    assert "aapl-20240928false2024FY" not in filing.body
    assert "http://fasb.org/us-gaap/" not in filing.body
    assert filing.body.rstrip().endswith("Apple Inc. | 2024 Form 10-K | 57")


# Fragments that only occur in XBRL residue: taxonomy URLs, unit and context tags.
XBRL_NOISE = re.compile(r"fasb\.org/us-gaap|xbrli:|iso4217:|us-gaap:\w+Member")


def test_no_cleaned_body_in_the_corpus_contains_xbrl_noise(corpus):
    filings = corpus

    raw_with_noise = [f for f in filings if XBRL_NOISE.search(f.path.read_text(encoding="utf-8"))]
    # The GE Filing (GE Capital's FY2014 10-K) predates inline XBRL: its only preamble is an
    # EDGAR document header.
    assert {f.path.name for f in filings} - {f.path.name for f in raw_with_noise} == {
        "GE_10K_2015-02-27_full.txt"
    }
    assert [f.path.name for f in filings if XBRL_NOISE.search(f.body)] == []
    assert all(f.xbrl_noise_chars > 0 for f in filings)


def test_table_of_contents_of_a_10k_is_located_in_the_cleaned_body():
    filing = load_filing(APPLE_10K)

    toc = filing.body[filing.toc.start : filing.toc.end]
    assert toc.startswith("| Page\nPart I\nItem 1. | Business | 1\nItem 1A. | Risk Factors | 5\n")
    assert toc.endswith("Item 16. | Form 10-K Summary | 56")
    assert filing.body[filing.toc.end :].lstrip().startswith("This Annual Report on Form 10-K")


def test_table_of_contents_of_a_10q_with_item_labels_on_their_own_rows():
    # Pfizer lists "Item 1. |" on one row and the heading and page on the next ones.
    filing = load_filing(DEFAULT_CORPUS_DIR / "PFE_10Q_2024Q1_2024-05-08_full.txt")

    toc = filing.body[filing.toc.start : filing.toc.end]
    assert filing.body[: filing.toc.start].endswith("TABLE OF CONTENTS\n")
    assert toc.startswith(
        "PART I.\xa0\xa0FINANCIAL INFORMATION | Page\nItem 1. |\nFinancial Statements |\n"
    )
    assert "Item 1A. |\nRisk Factors | 54\n" in toc
    assert toc.endswith("Item6. |\nExhibits | 55\nSignature | 55")


def test_large_jpmorgan_10k_is_cleaned_and_its_toc_located():
    filing = load_filing(DEFAULT_CORPUS_DIR / "JPM_10K_2026-02-13_full.txt")

    assert filing.xbrl_noise_chars > 200_000
    assert filing.body.startswith("UNITED STATES")
    assert XBRL_NOISE.search(filing.body) is None

    toc = filing.body[filing.toc.start : filing.toc.end]
    assert toc.startswith("Part I |  | Page\nItem 1. | Business. | 1\n")
    assert toc.endswith("Item 15. | Exhibits, Financial Statement Schedules. | 39-42")
    # The first real Item heading follows straight after the TOC.
    assert filing.body[filing.toc.end :].startswith("\nPart IItem 1. Business.Overview")


def test_filing_without_a_table_of_contents_has_none():
    # Disney's 10-Qs before 2025 go straight from the cover page to the statements.
    filing = load_filing(DEFAULT_CORPUS_DIR / "DIS_10Q_2024Q1_2024-05-07_full.txt")

    assert filing.toc is None


def test_every_toc_in_the_corpus_sits_near_the_front_of_the_body(corpus):
    filings = corpus

    without_toc = sorted(f.path.name for f in filings if f.toc is None)
    assert without_toc == [
        "DIS_10Q_2022Q1_2022-02-09_full.txt",
        "DIS_10Q_2022Q2_2022-05-11_full.txt",
        "DIS_10Q_2022Q3_2022-08-10_full.txt",
        "DIS_10Q_2022Q4_2023-02-08_full.txt",
        "DIS_10Q_2023Q2_2023-05-10_full.txt",
        "DIS_10Q_2023Q3_2023-08-09_full.txt",
        "DIS_10Q_2023Q4_2024-02-07_full.txt",
        "DIS_10Q_2024Q1_2024-05-07_full.txt",
        "DIS_10Q_2024Q2_2024-08-07_full.txt",
    ]
    for f in filings:
        if f.toc is not None:
            assert 0 < f.toc.start < f.toc.end < len(f.body) / 10, f.path.name


# --- Sectors and Tracked/Snapshot coverage ---------------------------------


def test_every_company_in_the_corpus_has_exactly_one_sector_row(corpus):
    rows_per_ticker = Counter(row.ticker for row in load_sector_table())

    assert set(rows_per_ticker) == {f.ticker for f in corpus}
    assert [t for t, n in rows_per_ticker.items() if n != 1] == []


def test_every_disagreement_between_sic_and_the_sector_label_is_explained():
    unexplained = [r.ticker for r in load_sector_table() if not r.sic_agrees and not r.note]

    assert unexplained == []


def test_health_care_companies_are_classified_by_what_they_do_not_by_sic_division():
    rows = {r.ticker: r for r in load_sector_table()}

    # SIC files UnitedHealth as an insurer and Thermo Fisher as an instrument maker.
    assert (rows["UNH"].sector, rows["UNH"].sic_code) == ("Health Care", "6324")
    assert rows["UNH"].industry == "Health Care Providers & Services"
    assert (rows["TMO"].sector, rows["TMO"].sic_code) == ("Health Care", "3829")
    assert rows["TMO"].industry == "Life Sciences Tools & Services"
    # The drug makers all share SIC 2834; GICS puts AbbVie in Biotechnology.
    pharma_sic = sorted(t for t, r in rows.items() if r.sic_code == "2834")
    assert pharma_sic == ["ABBV", "JNJ", "LLY", "MRK", "PFE"]
    assert all(rows[t].sector == "Health Care" for t in pharma_sic)
    assert {t for t in pharma_sic if rows[t].sic_agrees} == {"JNJ", "LLY", "MRK", "PFE"}


def test_every_filing_carries_its_companys_sector(corpus):
    nvda = _only(corpus, ticker="NVDA", report_period=date(2025, 7, 27))
    unh = next(f for f in corpus if f.ticker == "UNH")

    assert (nvda.sector, nvda.industry) == (
        "Information Technology",
        "Semiconductors & Semiconductor Equipment",
    )
    assert (unh.sector, unh.industry) == ("Health Care", "Health Care Providers & Services")
    assert [f.filing_id for f in corpus if not f.sector or not f.industry] == []


def test_companies_with_two_years_of_quarterly_filings_are_tracked_the_rest_snapshot(corpus):
    coverage = {f.ticker: f.coverage for f in corpus}

    tracked = {t for t, c in coverage.items() if c == "tracked"}
    assert tracked == {
        "AAPL", "AMZN", "DIS", "GOOG", "JNJ", "KO", "MSFT", "NVDA", "PFE", "TSLA", "UNH", "XOM",
        # Borderline: eight consecutive quarters, 2024Q1-2025Q4.
        "META",
    }  # fmt: skip
    # Borderline the other way: one year of quarters (BAC, JPM) or two scattered
    # Filings (MCD, PEP) cannot answer "over the last two years".
    assert {coverage[t] for t in ["BAC", "JPM", "MCD", "PEP", "GE", "LLY"]} == {"snapshot"}
    # Every Filing of a Company carries the same class.
    assert len({(f.ticker, f.coverage) for f in corpus}) == 54


# --- Sections: standard names, Item labels and coverage -------------------------

# Flattening often leaves four no-break spaces between an Item label and its title.
NBSP4 = "\xa0" * 4


def _section(filing, name):
    matches = [s for s in filing.sections if s.name == name]
    assert len(matches) == 1, f"expected one {name} Section, got {len(matches)}"
    return matches[0]


def test_10k_risk_factors_come_from_item_1a_and_mda_from_item_7():
    filing = load_filing(APPLE_10K)

    risk_factors = _section(filing, "Risk Factors")
    mda = _section(filing, "MD&A")

    assert risk_factors.item == "Item 1A"
    assert risk_factors.text.startswith(f"Item 1A.{NBSP4}Risk FactorsThe Company’s business")
    assert risk_factors.text.endswith("investor confidence and employee retention.")
    assert mda.item == "Item 7"
    assert mda.text.startswith(f"Item 7.{NBSP4}Management’s Discussion and Analysis")
    assert filing.body[mda.span.start : mda.span.end] == mda.text


def test_10q_mda_comes_from_part_i_item_2_and_risk_factors_from_part_ii_item_1a():
    filing = load_filing(DEFAULT_CORPUS_DIR / "AAPL_10Q_2025Q2_2025-08-01_full.txt")

    mda = _section(filing, "MD&A")
    risk_factors = _section(filing, "Risk Factors")

    assert mda.item == "Part I, Item 2"
    assert mda.text.startswith(f"Item 2.{NBSP4}Management’s Discussion and Analysis")
    assert risk_factors.item == "Part II, Item 1A"
    assert risk_factors.text.startswith(f"Item 1A.{NBSP4}Risk FactorsThe Company’s business")
    # Part I and Part II both have an Item 1; the title tells them apart.
    assert _section(filing, "Financial Statements").item == "Part I, Item 1"
    assert _section(filing, "Legal Proceedings").item == "Part II, Item 1"


def test_every_item_keeps_its_label_so_an_item_question_can_filter_on_it():
    filing = load_filing(APPLE_10K)

    labels = [s.item for s in filing.sections]
    item_7 = [s for s in filing.sections if s.item == "Item 7"]

    assert labels == [None] + [
        f"Item {n}" for n in "1 1A 1B 1C 2 3 4 5 6 7 7A 8 9 9A 9B 9C 10 11 12 13 14 15 16".split()
    ]
    assert [s.name for s in item_7] == ["MD&A"]
    assert _section(filing, "Cybersecurity").item == "Item 1C"
    assert {s.name for s in filing.sections if s.item in {"Item 2", "Item 15", "Item 16"}} == {
        "Other"
    }


def test_sections_cover_every_cleaned_body_exactly(corpus):
    for f in corpus:
        assert "".join(s.text for s in f.sections) == f.body, f.path.name
        assert f.sections[0].span.start == 0
        assert f.sections[-1].span.end == len(f.body)
        for before, after in zip(f.sections, f.sections[1:], strict=False):
            assert before.span.end == after.span.start, f.path.name
        unsectioned = [s for s in f.sections if s.item is None]
        assert all(s.name == UNSECTIONED for s in unsectioned), f.path.name
        assert all(s.name != UNSECTIONED for s in f.sections if s.item is not None)


def test_no_section_starts_inside_the_table_of_contents(corpus):
    for f in corpus:
        if f.toc is None:
            continue
        starts = [s.span.start for s in f.sections if s.item is not None]
        assert all(start >= f.toc.end for start in starts), f.path.name


def test_large_jpmorgan_10k_items_are_found_after_the_toc_and_its_mda_is_a_pointer():
    filing = load_filing(DEFAULT_CORPUS_DIR / "JPM_10K_2026-02-13_full.txt")

    risk_factors = _section(filing, "Risk Factors")
    mda = _section(filing, "MD&A")
    exhibits = next(s for s in filing.sections if s.item == "Item 15")

    assert [s.item for s in filing.sections][:3] == [None, "Item 1", "Item 1A"]
    assert len([s for s in filing.sections if s.item]) == 22  # every 10-K Item but Item 16
    assert risk_factors.text.startswith("Item 1A. Risk Factors. The following discussion")
    assert len(risk_factors.text) > 100_000
    # JPMorgan's Item 7 only points to the MD&A in the Annual Report appended after
    # Item 15, which therefore runs to the end of the body.
    assert mda.text.startswith("Item 7. Management’s Discussion and Analysis")
    assert "appears on pages 46–160" in mda.text
    assert len(mda.text) < 500
    assert exhibits.span.end == len(filing.body)
    assert "Management’s discussion and analysisThe following is" in exhibits.text
    assert [d for d in filing.diagnostics if d.code == "section_not_found"] == []


def test_a_section_that_cannot_be_found_is_reported_as_a_diagnostic():
    # Bank of America puts its name between the label and the title:
    # "Item 7. Bank of America Corporation and Subsidiaries\nManagement's Discussion".
    filing = load_filing(DEFAULT_CORPUS_DIR / "BAC_10K_2025-02-25_full.txt")

    assert "MD&A" not in {s.name for s in filing.sections}
    assert [(d.code, d.detail) for d in filing.diagnostics] == [
        ("section_not_found", "MD&A (Item 7)")
    ]
    # The MD&A text is not lost: it stays in the Item before it.
    item_6 = next(s for s in filing.sections if s.item == "Item 6")
    assert "Management's Discussion and Analysis" in item_6.text


def test_items_out_of_form_order_are_still_found():
    # Bank of America's 10-Qs open with MD&A (Part I, Item 2) and put the financial
    # statements (Part I, Item 1) after Items 3 and 4.
    filing = load_filing(DEFAULT_CORPUS_DIR / "BAC_10Q_2025Q1_2025-04-30_full.txt")

    labels = [s.item for s in filing.sections if s.item]

    assert labels[:4] == ["Part I, Item 2", "Part I, Item 3", "Part I, Item 4", "Part I, Item 1"]
    assert _section(filing, "MD&A").text.startswith("Item 2. Management’s Discussion")
    assert _section(filing, "Financial Statements").text.startswith(
        "Item 1. Financial StatementsBank of America Corporation"
    )
    assert [d for d in filing.diagnostics if d.code == "section_not_found"] == []


def test_rows_of_a_cross_reference_index_are_not_section_starts():
    # McDonald's 10-K uses its own headings and maps them to Items in a cross-reference
    # index near the end ("Item 1A | Risk Factors | Page28"). Those rows are not
    # headings, so the Items are reported missing rather than cut into one-row Sections.
    filing = load_filing(DEFAULT_CORPUS_DIR / "MCD_10K_2025-02-25_full.txt")

    assert [s.item for s in filing.sections if s.item] == []
    assert [d.detail for d in filing.diagnostics if d.code == "section_not_found"] == [
        "Business (Item 1)",
        "Risk Factors (Item 1A)",
        "Legal Proceedings (Item 3)",
        "MD&A (Item 7)",
        "Market Risk (Item 7A)",
        "Financial Statements (Item 8)",
        "Controls and Procedures (Item 9A)",
    ]


def test_a_heading_glued_to_its_title_is_found_when_the_title_starts_with_a_to_c(tmp_path):
    # "Item 1Business" is Item 1, not Item 1B, though B can follow an Item number. No
    # Filing in the Corpus glues these today, so a synthetic one isolates the case.
    path = tmp_path / "XYZ_10K_2025-02-01_full.txt"
    path.write_text(
        "Company: Example Corp\nTicker: XYZ\nFiling Type: 10-K (Annual Report)\n"
        "Filing Date: 2025-02-01\nCIK: 0000000001\nSource: SEC EDGAR\n"
        "URL: https://www.sec.gov/Archives/edgar/data/1/0001/xyz-20241231.htm\n"
        + "="
        * 60
        + "\n\nFORM 10-KFor the fiscal year ended December 31, 2024\n"
        "PART IItem 1Business. We make things.Item 1ARisk Factors. Things may break.\n"
        "Item 8Consolidated Financial Statements. The tables.\n"
        "Item 9Changes in and Disagreements with Accountants. None.\n",
        encoding="utf-8",
    )

    filing = load_filing(path)

    assert [s.item for s in filing.sections if s.item] == ["Item 1", "Item 1A", "Item 8", "Item 9"]


def test_heading_after_a_running_page_header_is_not_taken_for_a_cross_reference():
    # "...48Table of Contents ITEM 7A.    Quantitative and Qualitative Disclosures":
    # the words before the heading are page furniture, not a sentence citing it.
    filing = load_filing(DEFAULT_CORPUS_DIR / "LMT_10K_2026-01-29_full.txt")

    assert _section(filing, "MD&A").text.startswith(f"ITEM\xa07.{NBSP4}Management’s Discussion")
    assert _section(filing, "Market Risk").text.startswith(f"ITEM 7A.{NBSP4}Quantitative")
    assert [d for d in filing.diagnostics if d.code == "section_not_found"] == []


# --- Example questions: the Filings and Sections that should answer them --------


def _latest(filings, ticker, form_type):
    return max(
        (f for f in filings if f.ticker == ticker and f.form_type == form_type),
        key=lambda f: f.report_period,
    )


def test_each_example_question_company_has_a_latest_10k_with_substantive_risk_factors(corpus):
    # Analysis 8 answers the risk-factor questions from each Company's latest 10-K. Its
    # Item 1A must be found and hold the real discussion, not a pointer.
    latest = {
        t: _latest(corpus, t, "10-K")
        for t in ["AAPL", "TSLA", "JPM", "JNJ", "LLY", "MRK", "PFE", "ABBV"]
    }

    assert {t: f.filing_id for t, f in latest.items()} == {
        "AAPL": "AAPL_10-K_2025-09-27",
        "TSLA": "TSLA_10-K_2025-12-31",
        "JPM": "JPM_10-K_2025-12-31",
        "JNJ": "JNJ_10-K_2025-12-28",
        "LLY": "LLY_10-K_2025-12-31",
        # No FY2025 10-K in the Corpus for these three: their latest is FY2024.
        "MRK": "MRK_10-K_2024-12-31",
        "PFE": "PFE_10-K_2024-12-31",
        "ABBV": "ABBV_10-K_2024-12-31",
    }
    for ticker, filing in latest.items():
        risk_factors = _section(filing, "Risk Factors")
        assert risk_factors.item == "Item 1A", ticker
        assert len(risk_factors.text) > 20_000, ticker


def test_the_major_pharmaceutical_companies_resolve_through_the_sector_table():
    rows = load_sector_table()

    pharma = sorted(r.ticker for r in rows if r.industry in {"Pharmaceuticals", "Biotechnology"})

    assert pharma == ["ABBV", "JNJ", "LLY", "MRK", "PFE"]


def test_nvidias_last_two_years_are_eight_consecutive_quarters_up_to_its_latest_filing(corpus):
    nvda = sorted((f for f in corpus if f.ticker == "NVDA"), key=lambda f: f.report_period)
    anchor = nvda[-1].report_period

    # 52/53-week years drift by a few days, so two years back is taken with a week's
    # slack: NVIDIA's Q3 FY2024 ended on 29 October 2023, three days "after" 26 October.
    start = anchor.replace(year=anchor.year - 2) + timedelta(days=7)
    window = [f for f in nvda if f.report_period > start]

    assert anchor == date(2025, 10, 26)
    assert [f.fiscal_period for f in window] == [
        "FY2024", "Q1 FY2025", "Q2 FY2025", "Q3 FY2025",
        "FY2025", "Q1 FY2026", "Q2 FY2026", "Q3 FY2026",
    ]  # fmt: skip
    assert [f.form_type for f in window].count("10-K") == 2
    assert all(_section(f, "MD&A").text for f in window)
