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
table of contents is located.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from edgar_rag._body import Span, clean_body

DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[3] / "data" / "edgar_corpus"

_HEADER_END = "=" * 60

ReportPeriodSource = Literal["header", "url", "text"]

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
    fiscal_year_end_month: int | None = None
    fiscal_period: str | None = None
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def filing_id(self) -> str:
        """Stable identifier from Company, Form Type and Report Period."""
        return f"{self.ticker}_{self.form_type}_{self.report_period.isoformat()}"


def load_corpus(corpus_dir: str | Path = DEFAULT_CORPUS_DIR) -> list[Filing]:
    """Load every Filing listed in the Corpus manifest, in manifest order.

    Each Company's fiscal year end is derived from its 10-K Report Periods and every
    Filing gets its Fiscal Period from it.
    """
    corpus_dir = Path(corpus_dir)
    filings = [load_filing(corpus_dir / name) for name in _read_manifest(corpus_dir)["files"]]

    by_ticker: dict[str, list[Filing]] = defaultdict(list)
    for filing in filings:
        by_ticker[filing.ticker].append(filing)

    fiscal_year_ends: dict[str, int | None] = {}
    company_diagnostics: dict[str, tuple[Diagnostic, ...]] = {}
    for ticker, company_filings in by_ticker.items():
        months = Counter(
            _period_month(f.report_period)[1] for f in company_filings if f.form_type == "10-K"
        )
        fiscal_year_ends[ticker] = months.most_common(1)[0][0] if months else None
        company_diagnostics[ticker] = (
            (Diagnostic("fiscal_year_end_inconsistent", f"10-K months {sorted(months)}"),)
            if len(months) > 1
            else ()
        )

    return [
        _with_fiscal_period(
            replace(f, diagnostics=f.diagnostics + company_diagnostics[f.ticker]),
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
    )
    if fiscal_year_end_month is None and form_type == "10-K":
        fiscal_year_end_month = _period_month(report_period)[1]
    return _with_fiscal_period(filing, fiscal_year_end_month)


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
