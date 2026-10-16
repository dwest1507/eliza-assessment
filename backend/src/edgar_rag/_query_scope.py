"""Query Scope parser, internal to the retrieval seam.

Rule-based, with no LLM (ADR 0003). It recognises:

- Companies, by ticker and by name: the name in the Filings, the same name without its
  legal suffix ("Apple Inc" → "Apple"), and a few common aliases ("JPMorgan", "Google",
  "J&J").
- Time phrases: "latest" or "most recent", and "the last two years", "over the past 3
  quarters" and the like. A window is anchored on each Company's latest Filing, not on
  today's date (assumption 6).
- Section hints: risk factors, legal proceedings, MD&A, market risk and business.

Tickers match only when written in capitals, so "cost" never means Costco. Names match
in any case, except names that are also everyday words ("Target", "Meta", "Visa"),
which must be capitalised.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal


@dataclass(frozen=True)
class ScopeCompany:
    """A Company named in a question, with the coverage class its answers depend on."""

    ticker: str
    name: str
    coverage: str | None


# Aliases the Filing names don't yield by dropping a suffix.
_ALIASES: dict[str, tuple[str, ...]] = {
    "AMZN": ("Amazon",),
    "AXP": ("Amex",),
    "BAC": ("BofA",),
    "BRK": ("Berkshire",),
    "COST": ("Costco",),
    "CSCO": ("Cisco",),
    "DE": ("John Deere",),
    "DIS": ("Disney",),
    "GE": ("GE Capital",),
    "GOOG": ("Google",),
    "GS": ("Goldman",),
    "JNJ": ("J&J",),
    "JPM": ("JPMorgan", "JP Morgan", "J.P. Morgan"),
    "KO": ("Coca Cola", "Coke"),
    "LLY": ("Lilly",),
    "LMT": ("Lockheed",),
    "MCD": ("McDonald's", "McDonald’s"),
    "META": ("Meta", "Facebook"),
    "PEP": ("Pepsi",),
    "PG": ("P&G",),
    "RTX": ("Raytheon",),
    "TMO": ("Thermo Fisher",),
    "UPS": ("United Parcel Service",),
    "VZ": ("Verizon",),
    "XOM": ("Exxon", "ExxonMobil"),
}

# Names that are also everyday words: matched only when capitalised.
_COMMON_WORDS = {"apple", "target", "meta", "visa", "oracle", "intel", "chevron"}

_SUFFIX = re.compile(
    r"(?:,?\s+(?:(?:&|and)\s+)?(?:Inc|Incorporated|Corp|Corporation|Company|Co|Group|Holdings"
    r"|plc|Ltd)\.?)+$",
    re.I,
)
_THE = re.compile(r"^The\s+", re.I)


def find_companies(
    question: str, companies: Iterable[ScopeCompany]
) -> tuple[tuple[ScopeCompany, ...], list[tuple[int, int]]]:
    """The Companies a question names, in the order it first names them, and the
    character spans that name them."""
    companies = list(companies)
    found: dict[str, int] = {}
    taken: list[tuple[int, int]] = []
    patterns = sorted(_patterns(companies), key=lambda p: -len(p[1].pattern))
    by_ticker = {c.ticker: c for c in companies}
    for ticker, pattern in patterns:
        for m in pattern.finditer(question):
            if any(m.start() < end and start < m.end() for start, end in taken):
                continue  # inside a longer name already matched ("Morgan" in "JPMorgan")
            taken.append((m.start(), m.end()))
            found[ticker] = min(found.get(ticker, m.start()), m.start())
    named = tuple(by_ticker[t] for t in sorted(found, key=found.__getitem__))
    return named, sorted(taken)


def _patterns(companies: Iterable[ScopeCompany]) -> list[tuple[str, re.Pattern[str]]]:
    patterns = []
    for company in companies:
        patterns.append((company.ticker, re.compile(rf"(?<![\w$&]){re.escape(company.ticker)}\b")))
        for name in _names(company):
            flags = 0 if name.lower() in _COMMON_WORDS else re.I
            body = r"[\s\-]+".join(re.escape(word) for word in name.split())
            patterns.append((company.ticker, re.compile(rf"(?<!\w){body}(?!\w)", flags)))
    return patterns


def _names(company: ScopeCompany) -> set[str]:
    full = company.name.strip()
    short = _THE.sub("", _SUFFIX.sub("", full)).strip()
    names = {full, short, *_ALIASES.get(company.ticker, ())}
    if short.endswith(".com"):
        names.add(short.removesuffix(".com"))
    return {n for n in names if n}


# --- Time windows ------------------------------------------------------------------------


@dataclass(frozen=True)
class TimeWindow:
    """Which of each Company's Filings a question covers, anchored on the Company's
    latest Filing: every Filing, the latest 10-K plus any later 10-Qs, or the Filings
    whose Report Periods fall in the last `count` years, quarters or months."""

    kind: Literal["all", "latest", "years", "quarters", "months"]
    count: int | None = None

    @property
    def label(self) -> str:
        if self.kind == "all":
            return "all Filings"
        if self.kind == "latest":
            return "latest"
        unit = self.kind if self.count != 1 else self.kind.removesuffix("s")
        return f"last {self.count} {unit}"


ALL_FILINGS = TimeWindow("all")
LATEST = TimeWindow("latest")

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
}
_SPAN = re.compile(
    rf"\b(?:last|past|previous|prior|preceding)\s+(?:(\d{{1,2}}|{'|'.join(_NUMBER_WORDS)})\s+)?"
    r"(?:fiscal\s+)?(years?|quarters?|months?)\b",
    re.I,
)
_LATEST = re.compile(r"\b(?:latest|most\s+recent|newest)\b", re.I)

_DAYS = {"years": 365.25, "quarters": 365.25 / 4, "months": 365.25 / 12}
# A quarter-end within this many days after the window's start still counts as inside it.
# Half a quarter absorbs 52/53-week fiscal calendars, whose quarter-ends drift by days.
_SLACK_DAYS = 45


def find_time_window(question: str) -> TimeWindow | None:
    """The time phrase a question names, or None if it names none."""
    if m := _SPAN.search(question):
        count = m.group(1)
        n = 1 if count is None else int(count) if count.isdigit() else _NUMBER_WORDS[count.lower()]
        unit = m.group(2).lower()
        return TimeWindow(unit if unit.endswith("s") else unit + "s", max(n, 1))  # type: ignore[arg-type]
    if _LATEST.search(question):
        return LATEST
    return None


@dataclass(frozen=True)
class ScopeFiling:
    """A Filing inside the Query Scope's time window, with the periods an answer states."""

    filing_id: str
    ticker: str
    form_type: str
    report_period: str
    fiscal_period: str | None


def in_window(window: TimeWindow, filings: Sequence[ScopeFiling]) -> list[ScopeFiling]:
    """One Company's Filings that fall in the window, oldest first."""
    filings = sorted(filings, key=lambda f: f.report_period)
    if not filings or window.kind == "all":
        return filings
    if window.kind == "latest":
        annual = [i for i, f in enumerate(filings) if f.form_type == "10-K"]
        return filings[annual[-1] :] if annual else filings[-1:]
    anchor = date.fromisoformat(filings[-1].report_period)
    span = timedelta(days=round((window.count or 1) * _DAYS[window.kind]))
    start = min(anchor, anchor - span + timedelta(days=_SLACK_DAYS))
    return [f for f in filings if date.fromisoformat(f.report_period) >= start]


# --- Section hints -----------------------------------------------------------------------

# In order: a phrase matched by an earlier hint is not read again by a later one, so
# "interest rate risk" is Market Risk, not Risk Factors.
_SECTION_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (section, re.compile(pattern, re.I))
    for section, pattern in (
        (
            "Market Risk",
            r"\bmarket\s+risks?\b|\binterest[\s-]+rates?\s+risks?\b"
            r"|\b(?:currency|exchange[\s-]+rates?|commodity(?:\s+prices?)?)\s+risks?\b"
            r"|\bquantitative\s+and\s+qualitative\s+disclosures?\b",
        ),
        ("Legal Proceedings", r"\blegal\s+proceedings?\b|\blitigation\b|\blawsuits?\b"),
        (
            "MD&A",
            r"\bMD&A\b|\bmanagement[’']?s\s+discussion\b|\bresults\s+of\s+operations\b",
        ),
        (
            "Business",
            r"\bbusiness\s+(?:section|overview|description)\b"
            r"|\bdescription\s+of\s+(?:the|its|their)\s+business(?:es)?\b",
        ),
        ("Risk Factors", r"\brisk\s+factors?\b|\brisks?\b"),
    )
)


def find_section_hints(question: str) -> tuple[str, ...]:
    """The Sections a question hints at, in the order of `_SECTION_HINTS`."""
    found: list[str] = []
    for section, pattern in _SECTION_HINTS:
        question, n = pattern.subn(" ", question)
        if n:
            found.append(section)
    return tuple(found)
