"""The Corpus seam: load the whole Corpus, or one Filing, as Filing objects.

Header metadata is parsed as written. Every Filing also gets a Report Period, taken
from the header, else the date in the source URL, else the "fiscal year ended /
quarterly period ended" sentence on the cover page. All available sources are
cross-checked and disagreements are recorded as Diagnostics rather than raised.

Fiscal year ends are a Company-level fact, derived from the Company's 10-K Report
Periods, so `load_corpus` sets the Fiscal Period of every Filing. `load_filing` sets it
only when it knows the fiscal year end: from a 10-K's own Report Period, or when one
is passed in.

The body is cleaned: the XBRL noise in front of the cover page is removed and the
table of contents is located. The cleaned body is then split into Sections at its Item
headings, skipping the table of contents. Each Section carries its standard name and
its original Item label; text outside any Item is kept as an "Unsectioned" Section.

Every Filing carries its Company's Sector, industry and Company Group (if any) from the
curated Sector table (`data/reference/sectors.csv`). Coverage is also Company-level, so
only `load_corpus` classes each Company as a Tracked Company or a Snapshot Company.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from typing import Literal

from edgar_rag._body import Span, clean_body
from edgar_rag._sections import UNSECTIONED, Section, split_sections
from edgar_rag.paths import DATA_DIR

__all__ = [
    "DEFAULT_CORPUS_DIR",
    "DEFAULT_SECTOR_TABLE",
    "TRACKED_MIN_QUARTERS",
    "UNSECTIONED",
    "Coverage",
    "Diagnostic",
    "Filing",
    "ReportPeriodSource",
    "Section",
    "SectorRow",
    "Span",
    "check_manifest",
    "consecutive_quarters",
    "load_corpus",
    "load_filing",
    "load_sector_table",
    "report_quarter",
]

DEFAULT_CORPUS_DIR = DATA_DIR / "edgar_corpus"
DEFAULT_SECTOR_TABLE = DATA_DIR / "reference" / "sectors.csv"

_HEADER_END = "=" * 60

ReportPeriodSource = Literal["header", "url", "text"]
Coverage = Literal["tracked", "snapshot"]

# A Tracked Company has Filings for at least this many consecutive quarter-ends: two
# years, enough for "over the last two years" and a year-over-year comparison of every
# quarter. The Corpus has nothing between 4 (BAC, JPM) and 8 (META), so any cut-off
# from 5 to 8 gives the same split; 8 is the one that matches the question asked.
TRACKED_MIN_QUARTERS = 8

_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_MONTH_NUMBER = {name: i for i, name in enumerate(_MONTHS.split("|"), start=1)}

# A dated document name in the source URL, e.g. ".../aapl-20250927.htm" or
# ".../de-20251102x10k.htm". GE's ".../gecc10k2014.htm" has no date.
_URL_DATE = re.compile(r"-(\d{4})(\d{2})(\d{2})[^/]*$")

# The cover-page sentence. Between the phrase and the date the flattened text may hold
# nothing ("endedDecember"), table pipes, or another cell ("| Commission file |").
_DATE_AFTER = rf"[^0-9]{{0,80}}?({_MONTHS})\s*(\d{{1,2}})\s*,\s*(\d{{4}})"
_PERIOD_SENTENCE = {
    "10-K": re.compile(rf"for\s+the\s+(?:fiscal\s+)?year\s+ended{_DATE_AFTER}", re.I),
    "10-Q": re.compile(rf"for\s+the\s+quarterly\s+period\s+ended{_DATE_AFTER}", re.I),
}

# 52/53-week fiscal periods can end a few days into the next month (Coca-Cola's
# 2022-07-01, Deere's 2025-11-02). Such dates count as the end of the previous month.
_SPILLOVER_DAYS = 7


@dataclass(frozen=True)
class Diagnostic:
    """A metadata problem found while loading a Filing, kept for the EDA to report."""

    code: str
    detail: str


@dataclass(frozen=True)
class SectorRow:
    """One Company's row in the curated GICS-style Sector reference table."""

    ticker: str
    company: str
    sector: str
    industry: str
    sic_code: str
    sic_description: str
    sic_agrees: bool
    note: str
    group: str | None = None
    """The curated Company Group the Company belongs to ("Big Tech"), a named set of
    Companies no Sector captures, or None."""


@dataclass(frozen=True)
class Filing:
    """One 10-K or 10-Q submitted to the SEC by a single Company."""

    company: str
    ticker: str
    cik: str
    form_type: str
    filing_date: date
    report_period: date
    report_period_source: ReportPeriodSource
    calendar_quarter: str | None
    source_url: str
    path: Path
    body: str = field(repr=False)
    """The cleaned body: the Filing text after the header, with the XBRL noise removed."""
    xbrl_noise_chars: int
    """How many characters of XBRL noise were removed from the front of the raw body."""
    toc: Span | None
    """Where the table of contents sits in the cleaned body, or None if it has none.
    Section detection must skip it: TOC rows repeat the real Item headings."""
    sections: tuple[Section, ...] = field(default=(), repr=False)
    """The cleaned body split into Sections, in body order. Together they cover the
    whole body exactly."""
    fiscal_year_end_month: int | None = None
    fiscal_period: str | None = None
    sector: str | None = None
    industry: str | None = None
    group: str | None = None
    """The Company's curated Company Group from the Sector table, or None."""
    coverage: Coverage | None = None
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def filing_id(self) -> str:
        """Stable identifier from Company, Form Type and Report Period."""
        return f"{self.ticker}_{self.form_type}_{self.report_period.isoformat()}"


def load_corpus(corpus_dir: str | Path = DEFAULT_CORPUS_DIR) -> list[Filing]:
    """Load every Filing listed in the Corpus manifest, in manifest order.

    Each Company's fiscal year end is derived from its 10-K Report Periods and every
    Filing gets its Fiscal Period from it. Each Company is classed as a Tracked Company
    or a Snapshot Company from its coverage, and every Filing carries that class.
    """
    corpus_dir = Path(corpus_dir)
    filings = [load_filing(corpus_dir / name) for name in _read_manifest(corpus_dir)["files"]]

    by_ticker: dict[str, list[Filing]] = defaultdict(list)
    for filing in filings:
        by_ticker[filing.ticker].append(filing)

    fiscal_year_ends: dict[str, int | None] = {}
    coverage: dict[str, Coverage] = {}
    company_diagnostics: dict[str, tuple[Diagnostic, ...]] = {}
    for ticker, company_filings in by_ticker.items():
        months = Counter(
            _period_month(f.report_period)[1] for f in company_filings if f.form_type == "10-K"
        )
        fiscal_year_ends[ticker] = months.most_common(1)[0][0] if months else None
        tracked = consecutive_quarters(company_filings) >= TRACKED_MIN_QUARTERS
        coverage[ticker] = "tracked" if tracked else "snapshot"
        company_diagnostics[ticker] = (
            (Diagnostic("fiscal_year_end_inconsistent", f"10-K months {sorted(months)}"),)
            if len(months) > 1
            else ()
        )
        if company_filings[0].sector is None:
            company_diagnostics[ticker] += (
                Diagnostic("sector_missing", f"no row for {ticker} in the Sector table"),
            )

    return [
        _with_fiscal_period(
            replace(
                f,
                coverage=coverage[f.ticker],
                diagnostics=f.diagnostics + company_diagnostics[f.ticker],
            ),
            fiscal_year_ends[f.ticker],
        )
        for f in filings
    ]


def load_filing(path: str | Path, fiscal_year_end_month: int | None = None) -> Filing:
    """Load one Filing from its file in the Corpus.

    The Fiscal Period is set when `fiscal_year_end_month` is given, or when the Filing
    is a 10-K (its own Report Period marks the fiscal year end).
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    header = _parse_header(text, path)
    form_type = header["Filing Type"].split(" ", 1)[0]
    url = header["URL"]

    report_period, source, diagnostics = _resolve_report_period(
        header_value=header.get("Report Period"),
        url=url,
        body=text,
        form_type=form_type,
        name=path.name,
    )
    body = clean_body(_raw_body(text))
    sections, missing = split_sections(body.text, form_type, body.toc.end if body.toc else 0)
    diagnostics += tuple(Diagnostic("section_not_found", detail) for detail in missing)
    filing = Filing(
        company=header["Company"],
        ticker=header["Ticker"],
        cik=header["CIK"],
        form_type=form_type,
        filing_date=date.fromisoformat(header["Filing Date"]),
        report_period=report_period,
        report_period_source=source,
        calendar_quarter=header.get("Quarter"),
        source_url=url,
        path=path,
        diagnostics=diagnostics,
        body=body.text,
        xbrl_noise_chars=body.xbrl_noise_chars,
        toc=body.toc,
        sections=sections,
    )
    sector_row = _sector_rows(DEFAULT_SECTOR_TABLE).get(filing.ticker)
    if sector_row:
        filing = replace(
            filing,
            sector=sector_row.sector,
            industry=sector_row.industry,
            group=sector_row.group,
        )
    if fiscal_year_end_month is None and form_type == "10-K":
        fiscal_year_end_month = _period_month(report_period)[1]
    return _with_fiscal_period(filing, fiscal_year_end_month)


def consecutive_quarters(filings: Iterable[Filing]) -> int:
    """The longest run of consecutive quarter-ends covered by these Filings' Report Periods.

    A 10-K counts as its fiscal year's fourth quarter-end. Periods ending in the first
    days of a month count as the previous month's end, as for Fiscal Periods.
    """
    quarters = set()
    for filing in filings:
        year, month = _period_month(filing.report_period)
        quarters.add(year * 4 + (month - 1) // 3)
    longest = 0
    for start in quarters - {q + 1 for q in quarters}:
        run = 1
        while start + run in quarters:
            run += 1
        longest = max(longest, run)
    return longest


def report_quarter(report_period: date) -> str:
    """The calendar quarter whose end a Report Period stands for, as "2025Q3".

    Periods ending in the first days of a month count as the previous month's end, as
    for Fiscal Periods, so a 52/53-week quarter ending on 1 July is the second quarter.
    """
    year, month = _period_month(report_period)
    return f"{year}Q{(month - 1) // 3 + 1}"


def load_sector_table(path: str | Path = DEFAULT_SECTOR_TABLE) -> list[SectorRow]:
    """Read the curated Sector reference table, one row per Company, in file order."""
    with Path(path).open(encoding="utf-8", newline="") as f:
        return [
            SectorRow(
                ticker=row["ticker"],
                company=row["company"],
                sector=row["sector"],
                industry=row["industry"],
                sic_code=row["sic_code"],
                sic_description=row["sic_description"],
                sic_agrees=row["sic_agrees"] == "yes",
                note=row["note"],
                group=row["group"] or None,
            )
            for row in csv.DictReader(f)
        ]


@cache
def _sector_rows(path: Path) -> dict[str, SectorRow]:
    rows: dict[str, SectorRow] = {}
    for row in load_sector_table(path):
        if row.ticker in rows:
            raise ValueError(f"{path.name}: more than one Sector row for {row.ticker}")
        rows[row.ticker] = row
    return rows


def check_manifest(corpus_dir: str | Path = DEFAULT_CORPUS_DIR) -> list[str]:
    """Compare the manifest with the Filing files on disk. Returns the problems found."""
    corpus_dir = Path(corpus_dir)
    manifest = _read_manifest(corpus_dir)
    listed = list(manifest["files"])
    on_disk = sorted(p.name for p in corpus_dir.glob("*.txt"))

    problems = [f"missing on disk: {name}" for name in listed if name not in set(on_disk)]
    problems += [f"extra on disk: {name}" for name in on_disk if name not in set(listed)]
    problems += [f"listed twice: {name}" for name, n in Counter(listed).items() if n > 1]
    if manifest.get("file_count") != len(listed):
        problems.append(f"file_count is {manifest.get('file_count')} but {len(listed)} listed")
    return problems


def _read_manifest(corpus_dir: Path) -> dict:
    return json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))


def _parse_header(text: str, path: Path) -> dict[str, str]:
    end = text.find(_HEADER_END)
    if end == -1:
        raise ValueError(f"{path.name}: header separator not found")
    fields: dict[str, str] = {}
    for line in text[:end].splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def _raw_body(text: str) -> str:
    """Everything after the header separator line."""
    end = text.find("\n", text.find(_HEADER_END))
    return text[end + 1 :] if end != -1 else ""


def _resolve_report_period(
    *, header_value: str | None, url: str, body: str, form_type: str, name: str
) -> tuple[date, ReportPeriodSource, tuple[Diagnostic, ...]]:
    candidates: dict[ReportPeriodSource, date | None] = {
        "header": date.fromisoformat(header_value) if header_value else None,
        "url": _date_from_url(url),
        "text": _date_from_text(body, form_type),
    }
    found = {source: d for source, d in candidates.items() if d is not None}
    if not found:
        raise ValueError(f"{name}: no Report Period in header, URL or text")

    diagnostics: list[Diagnostic] = []
    if len(set(found.values())) > 1:
        detail = ", ".join(f"{source}={d.isoformat()}" for source, d in found.items())
        diagnostics.append(Diagnostic("report_period_mismatch", detail))
    if candidates["text"] is None:
        diagnostics.append(Diagnostic("report_period_text_missing", "no period sentence found"))

    source, report_period = next(iter(found.items()))
    return report_period, source, tuple(diagnostics)


def _date_from_url(url: str) -> date | None:
    match = _URL_DATE.search(url)
    if not match:
        return None
    try:
        return date(*(int(g) for g in match.groups()))
    except ValueError:
        return None


def _date_from_text(body: str, form_type: str) -> date | None:
    pattern = _PERIOD_SENTENCE.get(form_type)
    match = pattern.search(body) if pattern else None
    if not match:
        return None
    month, day, year = match.groups()
    try:
        return date(int(year), _MONTH_NUMBER[month.lower()], int(day))
    except ValueError:
        return None


def _period_month(d: date) -> tuple[int, int]:
    """The (year, month) whose end a period end date stands for."""
    if d.day <= _SPILLOVER_DAYS:
        d = d.replace(day=1) - timedelta(days=1)
    return d.year, d.month


MONTH_NAMES = (
    "January February March April May June July August September October November December"
).split()


def month_span(end_year: int, end_month: int, months: int) -> str:
    """The calendar months of a period `months` long that ends in month `end_month` (1 to
    12) of `end_year`: "May–Jul 2025" for a quarter, "Oct 2024–Sep 2025" for a year that
    crosses a calendar year."""
    end = end_year * 12 + end_month - 1
    (start_year, start), (_, end) = divmod(end - months + 1, 12), divmod(end, 12)
    first, last = MONTH_NAMES[start][:3], f"{MONTH_NAMES[end][:3]} {end_year}"
    return f"{first}–{last}" if start_year == end_year else f"{first} {start_year}–{last}"


def calendar_months(report_period: date | str, months: int) -> str:
    """The calendar months of a period `months` long (3 or 12) to a Report Period, ending
    in the month that date stands for (a 52/53-week period that ends in the first days of
    a month stands for the month before): "May–Jul 2025" for NVIDIA's quarter to
    2025-07-27, "Oct 2024–Sep 2025" for Apple's year to 2025-09-27."""
    if isinstance(report_period, str):
        report_period = date.fromisoformat(report_period)
    return month_span(*_period_month(report_period), months)


def filing_months(report_period: date | str, form_type: str) -> str:
    """The calendar months a Filing reports on: its year for a 10-K, its quarter for a
    10-Q."""
    return calendar_months(report_period, 12 if form_type.startswith("10-K") else 3)


def year_end_month(report_period: date | str) -> str:
    """The month a 10-K's Report Period ends its fiscal year in, named: "January" for
    NVIDIA's 2025-01-26, "June" for Microsoft's 2025-06-30."""
    if isinstance(report_period, str):
        report_period = date.fromisoformat(report_period)
    return MONTH_NAMES[_period_month(report_period)[1] - 1]


def _with_fiscal_period(filing: Filing, fiscal_year_end_month: int | None) -> Filing:
    if fiscal_year_end_month is None:
        return filing
    year, month = _period_month(filing.report_period)
    months_into_year = (month - fiscal_year_end_month) % 12
    fiscal_year = year + (1 if month > fiscal_year_end_month else 0)

    diagnostics = filing.diagnostics
    if months_into_year % 3:
        fiscal_period = None
        diagnostics += (
            Diagnostic(
                "fiscal_period_unaligned",
                f"period ends {months_into_year} months after fiscal year end month "
                f"{fiscal_year_end_month}",
            ),
        )
    elif filing.form_type == "10-K":
        fiscal_period = f"FY{fiscal_year}"
        if months_into_year:
            diagnostics += (
                Diagnostic("fiscal_period_unaligned", "10-K does not end a fiscal year"),
            )
    else:
        quarter = months_into_year // 3 or 4
        fiscal_period = f"Q{quarter} FY{fiscal_year}"
    return replace(
        filing,
        fiscal_year_end_month=fiscal_year_end_month,
        fiscal_period=fiscal_period,
        diagnostics=diagnostics,
    )
