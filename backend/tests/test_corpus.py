"""Tests through the Corpus seam, using real Corpus files as fixtures."""

import shutil
from datetime import date

import pytest

from edgar_rag.corpus import DEFAULT_CORPUS_DIR, check_manifest, load_corpus, load_filing


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


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
    assert filing.diagnostics == ()


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
    assert [d.code for d in filing.diagnostics] == ["report_period_mismatch"]
    assert "url=2024-12-31" in filing.diagnostics[0].detail
    assert "text=2024-09-30" in filing.diagnostics[0].detail


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
