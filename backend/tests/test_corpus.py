"""Tests through the Corpus seam, using real Corpus files as fixtures."""

from datetime import date

from edgar_rag.corpus import DEFAULT_CORPUS_DIR, load_corpus, load_filing


def test_filing_with_full_header_has_all_header_metadata():
    filing = load_filing(DEFAULT_CORPUS_DIR / "AAPL_10K_2024Q3_2024-11-01_full.txt")

    assert filing.company == "Apple Inc"
    assert filing.ticker == "AAPL"
    assert filing.cik == "0000320193"
    assert filing.form_type == "10-K"
    assert filing.filing_date == date(2024, 11, 1)
    assert filing.report_period == date(2024, 9, 28)
    assert filing.calendar_quarter == "2024Q3"
    assert filing.source_url == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    )


def test_filing_without_report_period_or_calendar_quarter_leaves_them_empty():
    filing = load_filing(DEFAULT_CORPUS_DIR / "AAPL_10K_2025-10-31_full.txt")

    assert filing.ticker == "AAPL"
    assert filing.form_type == "10-K"
    assert filing.filing_date == date(2025, 10, 31)
    assert filing.report_period is None
    assert filing.calendar_quarter is None


def test_load_corpus_returns_every_filing_in_the_manifest():
    filings = load_corpus()

    assert len(filings) == 246
    assert len({f.ticker for f in filings}) == 54
    form_types = [f.form_type for f in filings]
    assert form_types.count("10-K") == 89
    assert form_types.count("10-Q") == 157
