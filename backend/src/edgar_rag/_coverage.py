"""Coverage Gaps, internal to the retrieval seam.

A Coverage Gap is a part of a question the Corpus cannot answer. Code computes every gap
from the Query Scope and each Company's Filings, and words it the same way every time,
following EDA notebook section 8.6, so the Answer Call states it instead of filling it
from general knowledge:

- `snapshot_trend`: a trend asked of a Snapshot Company. Names the Filings the Corpus
  holds for it and the Report Periods they cover.
- `missing_company`: a Company the question names that is not in the Corpus,
  recognised through the curated list of notable missing Companies
  (`data/reference/missing_companies.csv`, assumption 9).
- `stale_filing`: GE Capital's FY2014 10-K, the only General Electric Filing. It is left
  out of every answer unless the question asks for GE Capital or its period by name
  (assumption 3).
- `no_guidance`: an outlook question. Guidance is published in earnings releases, which
  are not 10-K or 10-Q Filings (assumption 7).
- `periods_differ`: compared Companies whose latest Filings in scope cover different
  periods (assumption 6).

Each gap carries a short label (the callout's heading), the Companies it is about
(tickers, or names for missing Companies) and its full wording, which starts with the
label.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from edgar_rag._query_scope import (
    ScopeFiling,
    TimeWindow,
    company_patterns,
    names_period,
    short_name,
)

if TYPE_CHECKING:
    from edgar_rag.retrieval import QueryScope

DEFAULT_MISSING_COMPANIES = (
    Path(__file__).resolve().parents[3] / "data" / "reference" / "missing_companies.csv"
)

SNAPSHOT_TREND = "snapshot_trend"
MISSING_COMPANY = "missing_company"
STALE_FILING = "stale_filing"
NO_GUIDANCE = "no_guidance"
PERIODS_DIFFER = "periods_differ"

LABELS = {
    SNAPSHOT_TREND: "Trend unavailable",
    MISSING_COMPANY: "Not in the Corpus",
    STALE_FILING: "Stale Filing",
    NO_GUIDANCE: "No guidance in the Filings",
    PERIODS_DIFFER: "Periods differ",
}

COVERAGE_LABELS = {"tracked": "Tracked Company", "snapshot": "Snapshot Company"}


@dataclass(frozen=True)
class CoverageGap:
    """A part of the question the Corpus cannot answer, in its fixed wording."""

    kind: str
    """One of `snapshot_trend`, `missing_company`, `stale_filing`, `no_guidance`,
    `periods_differ`: the kinds the Golden Set labels."""
    label: str
    """The short heading the front-end's callout shows, e.g. "Trend unavailable"."""
    companies: tuple[str, ...]
    """Tickers of the Companies the gap is about, or names for Companies missing from the
    Corpus."""
    text: str
    """The wording the answer must state, starting with the label."""


@dataclass(frozen=True)
class CompanyCoverage:
    """What the Corpus holds for one Company in scope, as the prompt gives it."""

    ticker: str
    name: str
    coverage: str | None
    """`tracked` or `snapshot`."""
    filings: tuple[ScopeFiling, ...]
    """Every Filing of the Company in the Corpus, oldest first."""
    in_scope: tuple[ScopeFiling, ...]
    """The Filings inside the Query Scope's time window, oldest first."""
    left_out: tuple[ScopeFiling, ...]
    """Stale Filings left out of this answer."""


# --- Companies missing from the Corpus ----------------------------------------------------


@dataclass(frozen=True)
class MissingCompany:
    """A notable Company that is not in the Corpus, from the curated list."""

    name: str
    ticker: str
    aliases: tuple[str, ...]
    """Other names and the tickers to recognise. A ticker is matched only when written
    in capitals, and only if it is listed here."""
    sector: str
    industry: str


def load_missing_companies(
    path: str | Path = DEFAULT_MISSING_COMPANIES,
) -> tuple[MissingCompany, ...]:
    """Read the curated list of notable Companies missing from the Corpus."""
    return _load_missing_companies(Path(path))


@cache
def _load_missing_companies(path: Path) -> tuple[MissingCompany, ...]:
    with path.open(encoding="utf-8", newline="") as f:
        return tuple(
            MissingCompany(
                name=row["name"],
                ticker=row["ticker"],
                aliases=tuple(a.strip() for a in row["aliases"].split(";") if a.strip()),
                sector=row["sector"],
                industry=row["industry"],
            )
            for row in csv.DictReader(f)
        )


def find_missing(
    question: str, missing: Iterable[MissingCompany], taken: Sequence[tuple[int, int]]
) -> tuple[tuple[str, ...], list[tuple[int, int]]]:
    """The missing Companies a question names, by name, in the order it names them, and
    the spans that name them. Text inside `taken` (a Company in the Corpus or a Sector
    phrase) is not read again."""
    candidates = [
        (company.name, pattern)
        for company in missing
        for pattern in company_patterns(company.name, company.aliases)
    ]
    candidates.sort(key=lambda c: -len(c[1].pattern))
    used = list(taken)
    found: dict[str, int] = {}
    spans: list[tuple[int, int]] = []
    for name, pattern in candidates:
        for m in pattern.finditer(question):
            if any(m.start() < end and start < m.end() for start, end in used):
                continue
            used.append((m.start(), m.end()))
            spans.append((m.start(), m.end()))
            found[name] = min(found.get(name, m.start()), m.start())
    return tuple(sorted(found, key=found.__getitem__)), sorted(spans)


# --- Stale Filings -----------------------------------------------------------------------


@dataclass(frozen=True)
class StaleFiling:
    """A Filing that does not describe its Company today."""

    filing_id: str
    ticker: str
    filer: str
    """Who actually filed it, e.g. "GE Capital"."""
    asked_by: re.Pattern[str]
    """A question matching this asks for the Filing by name, so it may be cited."""


STALE_FILINGS = (
    StaleFiling(
        filing_id="GE_10-K_2014-12-31",
        ticker="GE",
        filer="GE Capital",
        asked_by=re.compile(r"\bGE\s+Capital\b|\bGeneral\s+Electric\s+Capital\b", re.I),
    ),
)
"""The GE Filing is GE Capital's 10-K for 2014: a different legal entity, a decade
before the rest of the Corpus (finding 3, assumption 3)."""


def stale_filings_left_out(
    question: str, periods: Sequence[str], filings: Iterable[ScopeFiling]
) -> dict[str, StaleFiling]:
    """The stale Filings to leave out of this answer, by Filing ID: all of them, except
    one the question asks for by its filer's name or by a period it covers."""
    by_id = {f.filing_id: f for f in filings}
    left_out = {}
    for stale in STALE_FILINGS:
        filing = by_id.get(stale.filing_id)
        if filing is None:
            continue
        asked = stale.asked_by.search(question) or names_period(filing.fiscal_period, periods)
        if not asked:
            left_out[stale.filing_id] = stale
    return left_out


# --- Trend and outlook questions ---------------------------------------------------------

_TREND = re.compile(
    r"\btrend(?:s|ed|ing)?\b|\bover\s+time\b|\byear[\s-]+(?:over|on)[\s-]+year\b"
    r"|\b(?:grown|grew)\b|\bchang(?:ed|ing)\b|\bevolv(?:e|ed|es|ing)\b|\bshifted\b"
    r"|\b(?:did|do|does|has|have)\s+(?:[\w’'&.-]+\s+){0,5}?(?<!climate\s)change\b",
    re.I,
)

_OUTLOOK = re.compile(
    r"\boutlook\b|\bguidance\b|\bforecasts?\b|\bprojections?\b|\bgoing\s+forward\b"
    r"|\b(?:next|coming)\s+(?:fiscal\s+)?(?:years?|quarters?)\b",
    re.I,
)

# The shortest span of each unit that asks for more than one quarter's Filings.
_MULTI_PERIOD = {"years": 1, "quarters": 2, "months": 4}


def asks_trend(question: str, window: TimeWindow) -> bool:
    """Whether a question asks how something moved over time: a trend or change word, or
    a time window longer than a quarter. "How do they differ" compares Companies, so it
    is not a trend."""
    if window.kind in _MULTI_PERIOD and (window.count or 1) >= _MULTI_PERIOD[window.kind]:
        return True
    return bool(_TREND.search(question))


def asks_outlook(question: str) -> bool:
    """Whether a question asks for an outlook, guidance or forecast."""
    return bool(_OUTLOOK.search(question))


# --- The gaps ----------------------------------------------------------------------------

_SAME_PERIOD_DAYS = 20
"""Latest Filings whose Report Periods are this close cover the same period: 52/53-week
calendars end a few days either side of the month-end."""


def coverage_gaps(
    question: str,
    scope: QueryScope,
    coverage: Sequence[CompanyCoverage],
) -> tuple[CoverageGap, ...]:
    """Every Coverage Gap of the question, in a fixed order: missing Companies, stale
    Filings, snapshot trends, periods that differ, then missing guidance."""
    gaps: list[CoverageGap] = []
    named = [c for c in coverage if c.ticker in {s.ticker for s in scope.companies}]
    for name in scope.missing_companies:
        gaps.append(
            _gap(
                MISSING_COMPANY,
                (name,),
                f"{name} is not in the Filings provided, so this answer does not cover it.",
            )
        )
    stale_ids = {s.filing_id: s for s in STALE_FILINGS}
    for company in named:
        for filing in company.filings:
            if stale := stale_ids.get(filing.filing_id):
                gaps.append(_stale_gap(company, filing, stale, filing in company.left_out))
    if asks_trend(question, scope.time_window):
        for company in named:
            if company.coverage != "tracked" and (usable := _usable(company)):
                gaps.append(_snapshot_gap(company, usable))
    if gap := _periods_gap(named):
        gaps.append(gap)
    if asks_outlook(question):
        if named:
            gaps += [
                _gap(
                    NO_GUIDANCE,
                    (c.ticker,),
                    f"{_possessive(short_name(c.name))} own guidance is not in the Filings "
                    "provided; the outlook below is drawn from MD&A commentary and risk "
                    "factors.",
                )
                for c in named
            ]
        elif not scope.missing_companies:
            gaps.append(
                _gap(
                    NO_GUIDANCE,
                    (),
                    "Companies' own guidance is not in the Filings provided; the outlook "
                    "below is drawn from MD&A commentary and risk factors.",
                )
            )
    return tuple(gaps)


def _gap(kind: str, companies: tuple[str, ...], wording: str) -> CoverageGap:
    return CoverageGap(kind, LABELS[kind], companies, f"{LABELS[kind]}: {wording}")


def _usable(company: CompanyCoverage) -> list[ScopeFiling]:
    return [f for f in company.filings if f not in company.left_out]


def _stale_gap(
    company: CompanyCoverage, filing: ScopeFiling, stale: StaleFiling, left_out: bool
) -> CoverageGap:
    name = short_name(company.name)
    only = "the only" if len(company.filings) == 1 else "a"
    period = filing.fiscal_period or filing.report_period
    use = (
        "so it is left out of this answer."
        if left_out
        else f"so it is cited here only as {_possessive(stale.filer)} report for {period}."
    )
    return _gap(
        STALE_FILING,
        (company.ticker,),
        f"{only} {name} Filing is {_possessive(stale.filer)} {filing.form_type} for {period} "
        f"(Report Period {filing.report_period}); it does not describe {name} today, {use}",
    )


def _snapshot_gap(company: CompanyCoverage, filings: Sequence[ScopeFiling]) -> CoverageGap:
    name = short_name(company.name)
    first, last = filings[0], filings[-1]
    count = f"{len(filings)} {name} Filing{'s' if len(filings) != 1 else ''}"
    span = _fiscal(first) if len(filings) == 1 else f"{_fiscal(first)} to {_fiscal(last)}"
    periods = (
        f"Report Period {first.report_period}"
        if len(filings) == 1
        else f"Report Periods {first.report_period} to {last.report_period}"
    )
    ids = ", ".join(f.filing_id for f in filings)
    return _gap(
        SNAPSHOT_TREND,
        (company.ticker,),
        f"{name} is a Snapshot Company. The Corpus holds {count}, {span} ({ids}), so this "
        f"answer covers {periods} only.",
    )


def _periods_gap(coverage: Sequence[CompanyCoverage]) -> CoverageGap | None:
    """The gap for compared Companies whose latest Filings in scope cover different
    periods. Each Company is placed by its latest 10-K in scope, or its latest Filing
    when the window holds no 10-K."""
    anchors = []
    for company in coverage:
        if not company.in_scope:
            continue
        annual = [f for f in company.in_scope if f.form_type == "10-K"]
        anchors.append((company, (annual or list(company.in_scope))[-1]))
    if len(anchors) < 2:
        return None
    ends = [date.fromisoformat(f.report_period) for _, f in anchors]
    if (max(ends) - min(ends)).days <= _SAME_PERIOD_DAYS:
        return None
    described = "; ".join(
        f"{short_name(c.name)}: {f.form_type} {_fiscal(f)}, "
        f"{'year' if f.form_type == '10-K' else 'quarter'} to {f.report_period}"
        for c, f in anchors
    )
    return _gap(
        PERIODS_DIFFER,
        tuple(c.ticker for c, _ in anchors),
        f"the Companies' latest Filings here cover different periods ({described}), so "
        "the comparison is not of the same period.",
    )


def _fiscal(filing: ScopeFiling) -> str:
    return filing.fiscal_period or f"period to {filing.report_period}"


def _possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"
