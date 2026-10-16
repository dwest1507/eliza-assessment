"""Query Scope parser, internal to the retrieval seam.

Rule-based, with no LLM (ADR 0003). It recognises:

- Companies, by ticker and by name: the name in the Filings, the same name without its
  legal suffix ("Apple Inc" → "Apple"), and a few common aliases ("JPMorgan", "Google",
  "J&J").
- Time phrases: "latest" or "most recent", and "the last two years", "over the past 3
  quarters" and the like. A window is anchored on each Company's latest Filing, not on
  today's date (assumption 6).
- Sector phrases ("the major pharmaceutical companies", "the major banks", "the oil
  majors"), resolved only through the sector and industry columns of the curated Sector
  table (assumption 5). Each phrase names table values, never Companies, so the Companies
  it covers are whatever the table says.
- Section hints: risk factors, legal proceedings, MD&A, market risk and business.
- Named periods: "FY2024", "fiscal 2024", "Q2 FY2025", or a bare year ("in 2023"), read
  as Fiscal Periods. A named period decides which copy of a repeated passage is cited.
- Change questions: "how has it changed", "what is new", "how did it evolve", "how do
  they differ". They are routed to the paragraphs new between periods.
- The metric of ADR 0001's vocabulary: "revenue", "sales" and "top line" are revenue;
  "net income", "earnings" and "profit" are net income.

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
    sector: str | None = None
    industry: str | None = None


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
    named, spans, _ = _find_named(question, companies)
    return named, spans


def _find_named(
    question: str, companies: Iterable[ScopeCompany]
) -> tuple[tuple[ScopeCompany, ...], list[tuple[int, int]], dict[str, int]]:
    """`find_companies`, plus where each named Company is first named."""
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
    return named, sorted(taken), found


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


# --- Sector phrases ----------------------------------------------------------------------


@dataclass(frozen=True)
class SectorPhrase:
    """A phrase naming a group of Companies, and the Sector table rows it resolved to."""

    phrase: str
    """The phrase as the question writes it, e.g. "pharmaceutical companies"."""
    column: Literal["sector", "industry"]
    """The Sector table column the phrase is read against."""
    values: tuple[str, ...]
    """The values of that column the phrase covers, e.g. ("Pharmaceuticals",
    "Biotechnology")."""
    tickers: tuple[str, ...]
    """The Companies whose row holds one of the values, by value and then ticker."""


# A word that makes a sector or industry word a group of Companies: "software companies",
# "the energy sector". Without one, "oil prices" or "software revenue" names no group.
_GROUP = (
    r"(?:companies|company\s+names|corporations|firms|groups|majors|makers|names|players"
    r"|producers|stocks|sector|industry|industries)"
)

# Each phrase is read against one column of the Sector table, in this order; text matched
# by an earlier phrase is not read again. The table, not this list, decides which
# Companies a phrase covers, so a disputed mapping is fixed in `sectors.csv`.
_SectorRule = tuple[re.Pattern[str], Literal["sector", "industry"], tuple[str, ...]]
_SECTOR_PHRASES: tuple[_SectorRule, ...] = tuple(
    (re.compile(pattern, re.I), column, values)
    for pattern, column, values in (
        (
            # AbbVie is Biotechnology in the GICS-style label but a drug maker by SIC
            # (2834), so it counts as a pharmaceutical company (assumption 5).
            rf"\bpharma(?:ceuticals?)?(?:\s+(?:and|&)\s+biotech(?:nology)?)?\s+{_GROUP}\b"
            r"|\bbig\s+pharma\b|\bpharmas\b|\bdrug[\s-]?makers\b|\bdrug\s+companies\b",
            "industry",
            ("Pharmaceuticals", "Biotechnology"),
        ),
        (rf"\bbiotech(?:nology)?\s+{_GROUP}\b|\bbiotechs\b", "industry", ("Biotechnology",)),
        (
            # Central banks are not Companies, and investment banks are Capital Markets.
            rf"(?<!central\s)(?<!investment\s)\b(?:banks\b|bank(?:ing)?\s+{_GROUP}\b"
            r"|bank\s+holding\s+companies\b)",
            "industry",
            ("Banks",),
        ),
        (
            rf"\boil(?:\s*(?:and|&)\s*gas)?\s+{_GROUP}\b",
            "industry",
            ("Oil, Gas & Consumable Fuels",),
        ),
        (rf"\bsoftware\s+{_GROUP}\b", "industry", ("Software",)),
        (
            rf"\b(?:semiconductor|chip)\s*-?\s*{_GROUP}\b|\bchipmakers\b",
            "industry",
            ("Semiconductors & Semiconductor Equipment",),
        ),
        (
            rf"\b(?:aerospace(?:\s+(?:and|&)\s+defen[cs]e)?|defen[cs]e)\s+(?:{_GROUP}|contractors)\b",
            "industry",
            ("Aerospace & Defense",),
        ),
        (
            r"\bretailers\b|\bretail\s+" + _GROUP + r"\b",
            "industry",
            ("Broadline Retail", "Specialty Retail", "Consumer Staples Distribution & Retail"),
        ),
        (
            rf"\b(?:auto|car)[\s-]?makers\b|\b(?:auto|automotive|car)\s+{_GROUP}\b",
            "industry",
            ("Automobiles",),
        ),
        (
            rf"\btelecom(?:munication)?s?\s+{_GROUP}\b|\btelcos\b|\bwireless\s+carriers\b",
            "industry",
            ("Diversified Telecommunication Services",),
        ),
        (rf"\b(?:beverage|soft\s+drinks?)\s+{_GROUP}\b", "industry", ("Beverages",)),
        (
            rf"\b(?:information\s+)?tech(?:nology)?\s+{_GROUP}\b",
            "sector",
            ("Information Technology",),
        ),
        (rf"\bhealth\s*care\s+{_GROUP}\b", "sector", ("Health Care",)),
        (
            rf"\bfinancials\b|\bfinancial\s+(?:{_GROUP}|institutions)\b",
            "sector",
            ("Financials",),
        ),
        (rf"\benergy\s+{_GROUP}\b", "sector", ("Energy",)),
        (rf"\bindustrials\b|\bindustrial\s+{_GROUP}\b", "sector", ("Industrials",)),
        (r"\bconsumer\s+staples\b", "sector", ("Consumer Staples",)),
        (r"\bconsumer\s+discretionary\b", "sector", ("Consumer Discretionary",)),
        (r"\bcommunication\s+services\b", "sector", ("Communication Services",)),
    )
)


def resolve_companies(
    question: str, companies: Iterable[ScopeCompany]
) -> tuple[tuple[ScopeCompany, ...], tuple[SectorPhrase, ...], list[tuple[int, int]]]:
    """The Companies a question covers, by name, ticker or Sector phrase, in the order
    the question first names them; the Sector phrases it uses; and the character spans
    of every name and phrase. A Company named both ways is listed once."""
    companies = sorted(companies, key=lambda c: c.ticker)
    _, spans, first = _find_named(question, companies)
    order = [(position, 0, ticker) for ticker, position in first.items()]
    phrases: list[tuple[int, SectorPhrase]] = []
    taken = list(spans)
    for pattern, column, values in _SECTOR_PHRASES:
        for m in pattern.finditer(question):
            if any(m.start() < end and start < m.end() for start, end in taken):
                continue  # part of a Company's name ("Bank of America") or an earlier phrase
            taken.append((m.start(), m.end()))
            tickers = tuple(
                c.ticker for value in values for c in companies if getattr(c, column) == value
            )
            phrases.append((m.start(), SectorPhrase(m.group(0), column, values, tickers)))
            order += [(m.start(), rank, t) for rank, t in enumerate(tickers, start=1)]
    by_ticker = {c.ticker: c for c in companies}
    covered = tuple(by_ticker[t] for _, _, t in sorted(order))
    unique = tuple(dict.fromkeys(covered))
    phrases.sort(key=lambda p: p[0])
    return unique, tuple(p for _, p in phrases), sorted(taken)


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


# --- Named periods -----------------------------------------------------------------------

_YEAR_DIGITS = r"((?:19|20)\d{2})"
_NAMED_QUARTER = re.compile(
    rf"\bQ([1-4])\s*(?:of\s+)?(?:FY\s?|fiscal\s+(?:year\s+)?)?{_YEAR_DIGITS}\b", re.I
)
_NAMED_FISCAL_YEAR = re.compile(rf"\b(?:FY\s?|fiscal\s+(?:year\s+)?){_YEAR_DIGITS}\b", re.I)
_NAMED_YEAR = re.compile(rf"\b{_YEAR_DIGITS}\b")


def find_periods(question: str) -> tuple[str, ...]:
    """The Fiscal Periods a question names, in the order it names them: "Q2 FY2025"
    for a quarter, "FY2024" for a fiscal year or a bare year."""
    found: list[tuple[int, str]] = []
    for pattern, label in (
        (_NAMED_QUARTER, lambda m: f"Q{m.group(1)} FY{m.group(2)}"),
        (_NAMED_FISCAL_YEAR, lambda m: f"FY{m.group(1)}"),
        (_NAMED_YEAR, lambda m: f"FY{m.group(1)}"),
    ):
        for m in pattern.finditer(question):
            found.append((m.start(), label(m)))
        question = pattern.sub(lambda m: " " * len(m.group(0)), question)
    return tuple(dict.fromkeys(label for _, label in sorted(found)))


def names_period(fiscal_period: str | None, periods: Sequence[str]) -> bool:
    """Whether a Filing's Fiscal Period is one the question names: the quarter itself,
    or any Filing of a named fiscal year."""
    if not fiscal_period:
        return False
    return any(
        fiscal_period == p or (p.startswith("FY") and fiscal_period.endswith(" " + p))
        for p in periods
    )


# --- Change questions --------------------------------------------------------------------

_CHANGE = re.compile(
    r"\bchang(?:ed|ing)\b|(?<!climate\s)\bchanges\b(?!\s+in\s+(?:the\s+)?climate)"
    r"|\bevolv(?:e|ed|es|ing)\b|\bdiffer(?:s|ed|ence|ences)?\b|\bshift(?:ed|s)?\b"
    r"|\b(?:what(?:[’']s|\s+is|\s+was)|anything)\s+new\b",
    re.I,
)


def is_change_question(question: str) -> bool:
    """Whether a question asks how something changed between periods."""
    return bool(_CHANGE.search(question))


# --- Metric ------------------------------------------------------------------------------

# ADR 0001's vocabulary. Segment names join it with the Financial Facts store.
_METRICS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (metric, re.compile(pattern, re.I))
    for metric, pattern in (
        ("net_income", r"\bnet\s+income\b|\bearnings\b|\bprofits?\b"),
        ("revenue", r"\brevenues?\b|\bsales\b|\btop[\s-]+line\b"),
    )
)


def find_metric(question: str) -> str | None:
    """The Financial Facts metric a question asks about (`revenue` or `net_income`), the
    one it names first if it names both, or None."""
    found = [(m.start(), metric) for metric, p in _METRICS if (m := p.search(question))]
    return min(found)[1] if found else None
