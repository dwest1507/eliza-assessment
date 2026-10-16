"""The Financial Facts seam: turn a Filing into Financial Facts read from its tables.

A Financial Fact is one reported figure: Company, Report Period, metric, value and
unit. Values are normalised to base units (US dollars, not "millions of dollars").

Only revenue is extracted so far. Filing tables survive in the cleaned body as rows of
`|`-separated cells, with the column headers (the periods) on rows of their own above
the figures and the scale ("in millions") in the table title or a header row. The
revenue figure for the Filing's own period is read from the Filing's income statement:

1. A table is a run of consecutive lines that contain a `|`.
2. A revenue row is a row whose label is one of the revenue labels the Companies use
   ("Revenues", "Total net sales", "Net Operating Revenues", "Sales to customers"...)
   and which holds figures. Within a table a label starting with "Total" wins over its
   parts ("Products", "Services").
3. The income statement is the first table titled as one ("Consolidated Statements of
   Operations", "Income Statements"...) with a revenue row and a net income row;
   failing that, the first table with both rows (a summary table); failing that, the
   first table with a revenue row.
4. The column comes from the nearest header row above the revenue row whose years
   line up with its figures: the first column of the Report Period's year, which in a
   10-Q is the three months ended. Columns are never taken by position alone, because
   Companies order them differently (most put the current year first, Alphabet's
   recent 10-Qs put it last). Percentage-change cells are dropped before columns are
   matched, and a leading note-reference column is skipped.
5. The scale ("in millions", "(millions of dollars)", "(MILLIONS") is the one stated
   nearest above the revenue row: in the header rows, else in the title above them.

A Filing yields no revenue fact rather than a guessed one when any step is ambiguous:
no revenue row, header years that don't line up with the figures, or no scale.

The seam is separate from the Corpus seam so the EDA can recommend dropping it
without touching the core.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from edgar_rag.corpus import Filing

__all__ = ["FinancialFact", "extract_financial_facts"]


@dataclass(frozen=True)
class FinancialFact:
    """One reported figure pulled from a Filing's tables."""

    ticker: str
    report_period: date
    metric: str
    value: int
    """In base units: whole US dollars."""
    unit: str
    filing_id: str
    period_months: int
    """Length of the period the value covers: 3 for a 10-Q quarter, 12 for a 10-K year."""
    label: str
    """The row label as written in the Filing, e.g. "Total net sales"."""
    scale: int
    """The multiplier applied to the figure as printed, e.g. 1,000,000 for "in millions"."""
    offset: int
    """Character offset of the source row in the Filing's cleaned body."""


def extract_financial_facts(filing: Filing) -> list[FinancialFact]:
    """The Financial Facts this Filing reports for its own period. Revenue only, so far."""
    revenue = _extract_revenue(filing)
    return [revenue] if revenue else []


# Labels Companies give their top-line revenue, compared after lower-casing, dropping
# footnote marks and a trailing colon.
_REVENUE_LABEL = re.compile(
    r"(?:total\s+)?(?:net\s+)?(?:sales|revenues?)(?:,?\s+net)?"
    r"|(?:total\s+)?net\s+operating\s+revenues?"
    r"|sales\s+to\s+customers"
    r"|sales\s+and\s+other\s+operating\s+revenues?"
    r"|total\s+revenues?\s+and\s+other\s+income"
    r"|total\s+revenues?,?\s+net\s+of\s+interest\s+expense"
)
_NET_INCOME_LABEL = re.compile(r"net\s+(?:income|earnings)\b")
_STATEMENT_TITLE = re.compile(
    r"statements?\s+of\s+(?:consolidated\s+)?(?:income|operations|earnings)"
    r"|income\s+statements?",
    re.IGNORECASE,
)

_SCALES = {"thousands": 1_000, "millions": 1_000_000, "billions": 1_000_000_000}
_SCALE = re.compile(
    r"\b(?:in|of)\s+(?:u\.s\.\s+)?(?:dollars\s+)?(thousands|millions|billions)\b"
    r"|\b(thousands|millions|billions)\s+of\s+(?:u\.s\.\s+)?dollars\b"
    r"|\(\s*(thousands|millions|billions)\b",
    re.IGNORECASE,
)
# How much text above the header row to search for the table title and its scale.
_CONTEXT_CHARS = 400
# How far above the revenue row its header row may be, and how far below it the net
# income row of an income statement.
_HEADER_SEARCH_ROWS = 15
_STATEMENT_ROWS = 40

_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_NUMBER = re.compile(r"\(?-?\$?\s*\d[\d,]*(?:\.\d+)?\s*\)?")
_DASHES = {"—", "–", "-"}
# Footnote marks and note references: "(1)", "(a)", "(Note 9)", a trailing "*".
_FOOTNOTE = re.compile(r"\s*\((?:\d{1,2}|[a-z]|note\s*\d+)\)|\s*\*+$", re.IGNORECASE)


@dataclass(frozen=True)
class _Row:
    label: str
    cells: tuple[str, ...]
    offset: int


def _extract_revenue(filing: Filing) -> FinancialFact | None:
    body = filing.body
    rows = _rows(body, filing.toc.end if filing.toc else 0)
    candidates = []
    for i in _revenue_rows(rows):
        header = _header_row(rows, i, len(_values(rows[i].cells)))
        if header is not None:
            candidates.append((_statement_rank(body, rows, header, i), i, header))
    for _, i, header in sorted(candidates):
        row = rows[i]
        values = _values(row.cells)
        years = _years(rows[header])
        values = values[len(values) - len(years) :]  # drop a leading note-reference column
        column = _column(years, filing.report_period)
        scale = _scale(body, rows, header, i)
        if column is None or scale is None or values[column] is None:
            continue
        return FinancialFact(
            ticker=filing.ticker,
            report_period=filing.report_period,
            metric="revenue",
            value=int(values[column] * scale),
            unit="USD",
            filing_id=filing.filing_id,
            period_months=12 if filing.form_type == "10-K" else 3,
            label=row.label,
            scale=scale,
            offset=row.offset,
        )
    return None


def _rows(body: str, start: int) -> list[_Row]:
    """Every line from `start` on, split into a label and cells at its `|`s.

    A line without a `|` (prose, or a table title) has no cells.
    """
    rows = []
    offset = start
    for line in body[start:].split("\n"):
        label, *cells = (cell.strip() for cell in line.split("|"))
        rows.append(_Row(label, tuple(cells), offset))
        offset += len(line) + 1
    return rows


def _norm(label: str) -> str:
    label = _FOOTNOTE.sub("", label.replace("\u00a0", " ")).strip().rstrip(":").strip()
    return re.sub(r"\s+", " ", label).lower()


def _is_data(row: _Row) -> bool:
    """A row of figures: some figure in it is not just a year heading a column."""
    return any(_NUMBER.fullmatch(c) and not _YEAR.fullmatch(c) for c in row.cells)


def _revenue_rows(rows: list[_Row]) -> list[int]:
    """Indexes of revenue rows, in body order. Within a table a "Total ..." row wins."""
    found = []
    table: list[int] = []
    for i, row in enumerate([*rows, _Row("", (), -1)]):
        if row.cells:
            if _REVENUE_LABEL.fullmatch(_norm(row.label)) and _values(row.cells):
                table.append(i)
            continue
        totals = [j for j in table if _norm(rows[j].label).startswith("total")]
        found += (totals or table)[:1]
        table = []
    return found


def _statement_rank(body: str, rows: list[_Row], header: int, i: int) -> int:
    """How surely the table of revenue row `i` is the income statement (0 is surest).

    0: titled as an income statement and has a net income row; 1: has a net income row
    (a summary table, say); 2: any other table with a revenue row.
    """
    width = len(_values(rows[i].cells))
    has_net_income = False
    for row in rows[i + 1 : i + 1 + _STATEMENT_ROWS]:
        if not row.cells:
            break
        if _NET_INCOME_LABEL.match(_norm(row.label)) and len(_values(row.cells)) == width:
            has_net_income = True
            break
    if not has_net_income:
        return 2
    title = body[max(0, rows[header].offset - _CONTEXT_CHARS) : rows[i].offset]
    return 0 if _STATEMENT_TITLE.search(title) else 1


def _values(cells: tuple[str, ...]) -> list[Decimal | None]:
    """The figures in a row, in column order, with percentage changes dropped.

    A dash stands for an empty figure and keeps its column (None).
    """
    values: list[Decimal | None] = []
    for cell in cells:
        if cell == "%" or cell.endswith("%"):
            if values and not cell.rstrip("%").strip():
                values.pop()  # the figure before a "%" cell is a percentage
            continue
        if cell in _DASHES:
            values.append(None)
        elif cell and _NUMBER.fullmatch(cell):
            values.append(_number(cell))
    return values


def _number(cell: str) -> Decimal | None:
    negative = cell.startswith("(") or cell.startswith("-")
    digits = re.sub(r"[^\d.]", "", cell)
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return -value if negative else value


def _years(row: _Row) -> list[int]:
    return [int(y) for y in _YEAR.findall(" | ".join((row.label, *row.cells)))]


def _header_row(rows: list[_Row], i: int, width: int) -> int | None:
    """The nearest header row above row `i` whose years head its `width` figures.

    One extra figure is allowed for a note-reference column in front of the figures.
    """
    for j in range(i - 1, max(-1, i - 1 - _HEADER_SEARCH_ROWS), -1):
        row = rows[j]
        if not row.cells or _is_data(row):
            continue
        if len(_years(row)) in (width, width - 1) and _years(row):
            return j
    return None


def _column(years: list[int], report_period: date) -> int | None:
    """The first column for the Report Period's year.

    A period ending in the first days of January (a 52/53-week year) may be headed with
    the previous year.
    """
    for year in (report_period.year, (report_period - timedelta(days=7)).year):
        if year in years:
            return years.index(year)
    return None


def _scale(body: str, rows: list[_Row], header: int, i: int) -> int | None:
    """The scale stated nearest above the revenue row: header rows, then the title."""
    texts = [" ".join((r.label, *r.cells)) for r in rows[header:i]]
    above = body[max(0, rows[header].offset - _CONTEXT_CHARS) : rows[header].offset]
    texts += reversed(above.split("\n"))
    for text in texts:
        match = _SCALE.search(text[-_CONTEXT_CHARS:])
        if match:
            return _SCALES[next(w for w in match.groups() if w).lower()]
    return None
