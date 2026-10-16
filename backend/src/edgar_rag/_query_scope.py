"""Query Scope parser, internal to the retrieval seam.

Rule-based, with no LLM (ADR 0003). This first version recognises Companies only, by
ticker and by name: the name in the Filings, the same name without its legal suffix
("Apple Inc" → "Apple"), and a few common aliases ("JPMorgan", "Google", "J&J").

Tickers match only when written in capitals, so "cost" never means Costco. Names match
in any case, except names that are also everyday words ("Target", "Meta", "Visa"),
which must be capitalised.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


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
