"""The Financial Facts store and its lookup, internal to the retrieval seam (ADR 0001).

At index time the Tracked Companies' Financial Facts (revenue, net income and segment
revenue) are read from each Filing by the Financial Facts seam and written to the
`financial_facts` table of the index. Nothing else is loaded into it: SEC XBRL data is
an evaluation reference, never a source of facts.

At question time one fixed parameterised query per Company and metric fetches the rows,
which are cut to the Query Scope's Filings (the periods the question names, or its time
window). Then:

- A fourth quarter is derived as a 10-K's fiscal year less its three 10-Q quarters, when
  the store holds all three, and labelled as derived. The 10-Qs it subtracts are cited
  even when they fall before the window, so the derived figure can be checked.
- A year-on-year change is derived for each row whose same period a year earlier is in
  the table, and labelled as derived.
- A segment series stops at a segment reorganisation: the latest run of Filings that
  report the same set of segments is kept, and a note says where the set changed.
- A Company and metric the store can't answer (a Snapshot Company, a metric or segment
  not extracted) gets a note that any figure for it must be read from the Filing text,
  and that the answer must say so.

Each Filing whose rows are used becomes one Facts Source, numbered before the text
Sources.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from edgar_rag._query_scope import ScopeCompany, ScopeFiling, names_period
from edgar_rag.corpus import Filing
from edgar_rag.financial_facts import extract_financial_facts

SCHEMA = """
CREATE TABLE financial_facts (
    filing_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    form_type TEXT NOT NULL,
    report_period TEXT NOT NULL,
    fiscal_period TEXT,
    metric TEXT NOT NULL,
    segment TEXT,
    value INTEGER NOT NULL,
    unit TEXT NOT NULL,
    period_months INTEGER NOT NULL,
    label TEXT NOT NULL,
    scale INTEGER NOT NULL
);
CREATE INDEX financial_facts_lookup ON financial_facts (ticker, metric);
"""

METRIC_NAMES = {
    "revenue": "Revenue",
    "net_income": "Net income",
    "segment_revenue": "Segment revenue",
}

FACTS_SECTION = "Financial Facts"


def store_rows(filing: Filing) -> list[tuple]:
    """The `financial_facts` rows of one Filing: its extracted facts if its Company is
    Tracked, else none (ADR 0001: Snapshot Companies stay out until measured)."""
    if filing.coverage != "tracked":
        return []
    return [
        (
            fact.filing_id,
            fact.ticker,
            filing.form_type,
            fact.report_period.isoformat(),
            filing.fiscal_period,
            fact.metric,
            fact.segment,
            fact.value,
            fact.unit,
            fact.period_months,
            fact.label,
            fact.scale,
        )
        for fact in extract_financial_facts(filing)
    ]


def segment_names(db: sqlite3.Connection, tickers: Sequence[str]) -> dict[str, list[str]]:
    """Each Company's segment names as its Filings print them."""
    if not tickers:
        return {}
    names: dict[str, list[str]] = {}
    for row in db.execute(
        "SELECT DISTINCT ticker, segment FROM financial_facts "
        f"WHERE metric = 'segment_revenue' AND ticker IN ({', '.join('?' * len(tickers))}) "
        "ORDER BY ticker, segment",
        tuple(tickers),
    ):
        names.setdefault(row[0], []).append(row[1])
    return names


@dataclass(frozen=True)
class FactRow:
    """One row of the Financial Facts table in the Answer Call's prompt: a figure
    reported by one Filing, or one derived from reported figures."""

    ticker: str
    company: str
    metric: str
    """`revenue`, `net_income` or `segment_revenue`."""
    segment: str | None
    fiscal_period: str
    """"Q3 FY2026" for a quarter, "FY2025" for a fiscal year."""
    report_period: str
    months: int
    """The length of the period the value covers: 3 or 12."""
    value: int
    """In whole US dollars."""
    filing_id: str | None
    """The Filing that reports it, or None for a derived figure."""
    label: str | None = None
    """The row label as the Filing prints it; None for a derived figure."""
    derived: str | None = None
    """How a derived figure was computed, e.g. "FY2025 less Q1–Q3 FY2025"."""
    sources: tuple[str, ...] = ()
    """The tags of the Facts Sources the figure comes from."""
    year_on_year: float | None = None
    """The derived change from the same period a year earlier, as a fraction."""
    year_on_year_sources: tuple[str, ...] = ()
    """The tags of the Facts Sources of both periods of the change."""

    @property
    def value_text(self) -> str:
        """The value in millions of dollars, e.g. "$57,006 million"."""
        return money(self.value)

    @property
    def metric_name(self) -> str:
        name = METRIC_NAMES[self.metric]
        return f"{name}: {self.segment}" if self.segment else name


@dataclass(frozen=True)
class FactNote:
    """Something the Financial Facts can't answer, stated in the prompt."""

    kind: Literal["text_fallback", "segments_changed"]
    ticker: str
    metric: str
    text: str


@dataclass(frozen=True)
class Lookup:
    """The Financial Facts for a Query Scope, before Source numbering."""

    rows: tuple[FactRow, ...]
    notes: tuple[FactNote, ...]
    filings: tuple[tuple[str, str], ...]
    """The (ticker, Filing ID) of every Filing the rows come from, in citing order."""
    reported: dict[str, tuple[FactRow, ...]]
    """Each of those Filings' reported rows: its rows in the table, and the 10-Q rows a
    derived fourth quarter subtracts."""


_FISCAL = re.compile(r"^(?:Q([1-4]) )?FY(\d{4})$")


def lookup(
    db: sqlite3.Connection,
    companies: Sequence[ScopeCompany],
    metrics: Sequence[str],
    segments: Sequence[str],
    filings: Sequence[ScopeFiling],
    periods: Sequence[str],
) -> Lookup:
    """The rows, notes and cited Filings for these Companies and metrics, within the
    Query Scope's Filings (`filings`) or the Fiscal Periods it names (`periods`)."""
    rows: list[FactRow] = []
    notes: list[FactNote] = []
    reported: dict[str, dict[FactRow, None]] = {}
    for company in companies:
        for metric in metrics:
            found, components, found_notes = _company_metric(
                db, company, metric, segments, filings, periods
            )
            rows += found
            notes += found_notes
            for row in [r for r in found if r.filing_id] + components:
                reported.setdefault(row.filing_id or "", {}).setdefault(row)
    rows = _with_year_on_year(rows)
    cited = {(r.ticker, f): None for r in rows for f in r.sources}
    order = {c.ticker: i for i, c in enumerate(companies)}
    ordered = sorted(cited, key=lambda k: (order[k[0]], k[1].rsplit("_", 1)[-1], k[1]))
    return Lookup(
        rows=tuple(rows),
        notes=tuple(notes),
        filings=tuple(ordered),
        reported={f: tuple(r) for f, r in reported.items()},
    )


def _company_metric(
    db: sqlite3.Connection,
    company: ScopeCompany,
    metric: str,
    segments: Sequence[str],
    filings: Sequence[ScopeFiling],
    periods: Sequence[str],
) -> tuple[list[FactRow], list[FactRow], list[FactNote]]:
    """The table's rows for one Company and metric, the reported rows a derived figure
    subtracts, and the notes."""
    what = METRIC_NAMES[metric].lower()
    if metric == "segment_revenue" and segments:
        what = f"segment revenue ({', '.join(segments)})"
    name = f"{company.name} ({company.ticker})"
    if company.coverage != "tracked":
        return (
            [],
            [],
            [
                _fallback(
                    company,
                    metric,
                    f"{name} is a Snapshot Company, so no Financial Facts are extracted for it. "
                    f"Any {what} figure for it must be read from the Sources' text.",
                )
            ],
        )
    stored = db.execute(
        "SELECT * FROM financial_facts WHERE ticker = ? AND metric = ? "
        "ORDER BY report_period, segment",
        (company.ticker, metric),
    ).fetchall()
    if periods:
        in_scope = {r["filing_id"] for r in stored if names_period(r["fiscal_period"], periods)}
    else:
        in_scope = {f.filing_id for f in filings if f.ticker == company.ticker}
    chosen = [r for r in stored if r["filing_id"] in in_scope]
    notes: list[FactNote] = []
    if metric == "segment_revenue":
        chosen, change = _latest_segment_run(chosen)
        if change:
            notes.append(FactNote("segments_changed", company.ticker, metric, f"{name}: {change}"))
        if segments:
            chosen = [r for r in chosen if r["segment"] in segments]
    if not chosen:
        notes.append(
            _fallback(
                company,
                metric,
                f"No {what} Financial Facts were extracted from {name}'s Filings in the "
                f"Query Scope. Any {what} figure for it must be read from the Sources' text.",
            )
        )
        return [], [], notes
    rows = [_reported(company, r) for r in chosen]
    derived, components = _fourth_quarters(company, chosen, stored)
    rows = sorted(rows + derived, key=lambda r: (r.segment or "", r.report_period, r.months))
    return rows, components, notes


def _fallback(company: ScopeCompany, metric: str, text: str) -> FactNote:
    return FactNote(
        "text_fallback",
        company.ticker,
        metric,
        text + " The answer must say such a figure was read from the Filing text, not from "
        "extracted Financial Facts.",
    )


def _reported(company: ScopeCompany, r: sqlite3.Row) -> FactRow:
    return FactRow(
        ticker=company.ticker,
        company=company.name,
        metric=r["metric"],
        segment=r["segment"],
        fiscal_period=r["fiscal_period"],
        report_period=r["report_period"],
        months=r["period_months"],
        value=r["value"],
        filing_id=r["filing_id"],
        label=r["label"],
        sources=(r["filing_id"],),
    )


def _segment_sets(rows: Sequence[sqlite3.Row]) -> dict[str, frozenset[str]]:
    sets: dict[str, set[str]] = {}
    for r in rows:
        sets.setdefault(r["filing_id"], set()).add(r["segment"])
    return {k: frozenset(v) for k, v in sets.items()}


def _latest_segment_run(rows: list[sqlite3.Row]) -> tuple[list[sqlite3.Row], str | None]:
    """The rows of the latest run of Filings reporting the same set of segments, and a
    sentence saying where the set changed, if it did. Filings with no segment facts are
    gaps in extraction, not changes."""
    sets = _segment_sets(rows)
    by_filing = sorted({(r["report_period"], r["filing_id"], r["fiscal_period"]) for r in rows})
    if not by_filing:
        return rows, None
    latest = sets[by_filing[-1][1]]
    start = len(by_filing) - 1
    while start > 0 and sets[by_filing[start - 1][1]] == latest:
        start -= 1
    if start == 0:
        return rows, None
    before, after = by_filing[start - 1], by_filing[start]
    old = sets[before[1]]
    dropped, added = sorted(old - latest), sorted(latest - old)
    change = (
        f"the segments it reports changed between {before[2]} ({before[1]}) and "
        f"{after[2]} ({after[1]})"
    )
    details = []
    if dropped:
        details.append(f"no longer reported: {', '.join(dropped)}")
    if added:
        details.append(f"new: {', '.join(added)}")
    if details:
        change += f" ({'; '.join(details)})"
    change += (
        f". The segment series stops at that reorganisation and starts at {after[2]}: "
        "segment figures from before it are not comparable and are left out."
    )
    kept = {f[1] for f in by_filing[start:]}
    return [r for r in rows if r["filing_id"] in kept], change


def _fourth_quarters(
    company: ScopeCompany, chosen: list[sqlite3.Row], stored: list[sqlite3.Row]
) -> tuple[list[FactRow], list[FactRow]]:
    """A fourth quarter for each fiscal year in `chosen`, derived as the 10-K's year less
    the three 10-Q quarters of the same fiscal year in the store, when it holds all three
    (for a segment, all reporting the same set of segments as the 10-K)."""
    sets = _segment_sets(stored)
    derived: list[FactRow] = []
    components: list[FactRow] = []
    for annual in chosen:
        m = _FISCAL.match(annual["fiscal_period"] or "")
        if annual["period_months"] != 12 or not m or m.group(1):
            continue
        year = m.group(2)
        quarters = []
        for q in (1, 2, 3):
            match = [
                r
                for r in stored
                if r["fiscal_period"] == f"Q{q} FY{year}"
                and r["period_months"] == 3
                and r["segment"] == annual["segment"]
                and (annual["segment"] is None or sets[r["filing_id"]] == sets[annual["filing_id"]])
            ]
            if len(match) != 1:
                break
            quarters.append(match[0])
        else:
            components += [_reported(company, r) for r in quarters]
            derived.append(
                FactRow(
                    ticker=company.ticker,
                    company=company.name,
                    metric=annual["metric"],
                    segment=annual["segment"],
                    fiscal_period=f"Q4 FY{year}",
                    report_period=annual["report_period"],
                    months=3,
                    value=annual["value"] - sum(r["value"] for r in quarters),
                    filing_id=None,
                    derived=f"FY{year} less Q1–Q3 FY{year}",
                    sources=(annual["filing_id"], *(r["filing_id"] for r in quarters)),
                )
            )
    return derived, components


def _with_year_on_year(rows: list[FactRow]) -> list[FactRow]:
    """Each row with its change from the same period a year earlier, when that row is in
    the table too and its value is positive."""
    by_key = {(r.ticker, r.metric, r.segment, r.months, r.fiscal_period): r for r in rows}
    out = []
    for row in rows:
        m = _FISCAL.match(row.fiscal_period or "")
        prior = None
        if m:
            quarter = f"Q{m.group(1)} " if m.group(1) else ""
            earlier = f"{quarter}FY{int(m.group(2)) - 1}"
            prior = by_key.get((row.ticker, row.metric, row.segment, row.months, earlier))
        if prior is not None and prior.value > 0:
            row = replace(
                row,
                year_on_year=(row.value - prior.value) / prior.value,
                year_on_year_sources=tuple(dict.fromkeys(row.sources + prior.sources)),
            )
        out.append(row)
    return out


def with_tags(lookup: Lookup, tags: dict[str, str]) -> tuple[FactRow, ...]:
    """The rows with Filing IDs replaced by the tags of their Facts Sources."""
    return tuple(
        replace(
            r,
            sources=tuple(tags[f] for f in r.sources),
            year_on_year_sources=tuple(tags[f] for f in r.year_on_year_sources),
        )
        for r in lookup.rows
    )


def money(value: int) -> str:
    """A dollar value in millions, as "$130,497 million" or "-$460 million"."""
    millions = f"{abs(value) / 1_000_000:,.3f}".rstrip("0").rstrip(".")
    return f"{'-' if value < 0 else ''}${millions} million"


def percent(change: float) -> str:
    return f"{change * 100:+.1f}%"


def as_text(tag: str, reported: Sequence[FactRow], table: Sequence[FactRow]) -> str:
    """The text of the Facts Source `tag`, one line per figure: each row it reports,
    with its year-on-year change when the table derives one, then each fourth quarter
    derived from it first (from a 10-K's year)."""

    def change(row: FactRow | None) -> str:
        if row is None or row.year_on_year is None:
            return ""
        return f"; {percent(row.year_on_year)} from a year earlier (derived)"

    in_table = {
        (r.metric, r.segment, r.months, r.fiscal_period): r for r in table if r.sources == (tag,)
    }
    lines = [
        f"{r.metric_name}, {r.fiscal_period}, {r.months} months ended {r.report_period}: "
        f'{money(r.value)} (reported as "{r.label}")'
        + change(in_table.get((r.metric, r.segment, r.months, r.fiscal_period)))
        for r in reported
    ]
    lines += [
        f"{r.metric_name}, {r.fiscal_period}, {r.months} months ended {r.report_period}: "
        f"{money(r.value)} (derived: {r.derived})" + change(r)
        for r in table
        if r.derived and r.sources[:1] == (tag,)
    ]
    return "\n".join(lines)
