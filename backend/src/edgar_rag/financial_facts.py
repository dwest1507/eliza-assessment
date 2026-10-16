"""The Financial Facts seam: turn a Filing into Financial Facts read from its tables.

A Financial Fact is one reported figure: Company, Report Period, metric, value and
unit. Values are normalised to base units (US dollars, not "millions of dollars").

Three metrics are extracted: `revenue`, `net_income` and `segment_revenue` (one fact
per segment, named in `FinancialFact.segment`). Per-share values (earnings per share)
are not extracted, and are never read as one of these metrics.

Filing tables survive in the cleaned body as rows of `|`-separated cells, with the
column headers (the periods) on rows of their own above the figures and the scale
("in millions") in the table title or a header row. Revenue and net income for the
Filing's own period are read from the Filing's income statement:

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
6. Net income is the row below revenue, in the same table and column, labelled net
   income or net earnings. Net income attributable to the Company ("... attributable
   to ExxonMobil") wins over the total including noncontrolling interests, matching
   what the SEC reports as `NetIncomeLoss`. Rows per share, for continuing or
   discontinued operations, or attributable to noncontrolling interests never count.

Segment revenue is read from the first segment table that reconciles to revenue:

7. A table is split at each of its header rows, since a page footer containing a `|`
   can glue separate tables into one run of lines.
8. Segments are either rows of figures directly above a row equal to revenue (a
   subtotal replaces the rows it adds up; a dash for the period is nil), or heading
   rows each followed by its own revenue row ("North America", then "Net sales").
9. The text introducing them (the label rows above them, or the last sentence of the
   paragraph above the table) must call them segments, which keeps out tables of
   products, geographies and end markets that also add up to revenue.
10. Their figures, with reconciling rows (eliminations, hedging, corporate), must add
   up to revenue. The reconciling rows are not segments and yield no facts.

A Filing yields no fact rather than a guessed one when any step is ambiguous: no
revenue row, header years that don't line up with the figures, no scale, or segments
that don't add up. Without a revenue fact it yields no facts at all, since net income
and segments are located and checked against it.

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
    segment: str | None = None
    """The segment a segment revenue figure belongs to, as the Filing names it."""


def extract_financial_facts(filing: Filing) -> list[FinancialFact]:
    """The Financial Facts this Filing reports for its own period.

    Revenue and net income from the income statement, then segment revenue. A Filing
    whose revenue cannot be read yields no facts at all, since the other metrics are
    located and checked against it.
    """
    statement = _income_statement(filing)
    if statement is None:
        return []
    revenue = statement.fact("revenue", statement.anchor)
    facts = [revenue]
    net_income_row = _net_income_row(statement)
    if net_income_row is not None:
        facts.append(statement.fact("net_income", net_income_row))
    return facts + _segment_revenue(filing, statement.rows, revenue)


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
# The net income row itself: "Net income", "Net earnings/(loss)", "Consolidated net
# income", "Net income including noncontrolling interests", or net income attributable
# to the Company ("... attributable to ExxonMobil"), never to noncontrolling interests.
_NET_INCOME_ROW = re.compile(
    r"(?:consolidated\s+)?net\s+(?:\(loss\)\s+)?(?:income|earnings)(?:\s*/?\s*\(loss\))?"
    r"(?:\s+(?P<attributable>attributable\s+to\s+(?!noncontrolling).+)"
    r"|\s+(?:including|before\s+allocation\s+to)\s+noncontrolling\s+interests)?"
)
_SEGMENT = re.compile(r"\bsegments?\b", re.IGNORECASE)
# Rows in a segment table that reconcile segments to the total but are not segments.
_RECONCILING = re.compile(
    r"eliminat|hedging|corporate|reconcil|unallocated|intersegment", re.IGNORECASE
)
# How far above segment rows to look for the text that introduces them, how long a
# text may be to be read whole, and where a long one's last sentence starts.
_INTRO_ROWS = 8
_SHORT_TEXT = 120
_SENTENCE_BREAK = re.compile(r"[.:•]\s*(?=[A-Z(\u201c])|\.\s")
_TOTAL_HEADING = re.compile(r"total|consolidated(?:\s+totals?)?|total\s+consolidated")
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
_NUMBER = re.compile(r"\$?\s*\(?-?\$?\s*\d[\d,]*(?:\.\d+)?\s*\)?")
_DASHES = {"—", "–", "-"}
# Footnote marks and note references: "(1)", "(a)", "(Note 9)", a trailing "*".
_FOOTNOTE = re.compile(r"\s*\((?:\d{1,2}|[a-z]|note\s*\d+)\)|\s*\*+$", re.IGNORECASE)


@dataclass(frozen=True)
class _Row:
    label: str
    cells: tuple[str, ...]
    offset: int


@dataclass(frozen=True)
class _Table:
    """A table of a Filing, with its Report Period column and scale located.

    `anchor` is the row the header and scale were located from: the revenue row of
    the income statement, or the first row of figures in a segment table.
    """

    filing: Filing
    rows: list[_Row]
    anchor: int
    years: int
    """How many year columns the header row heads."""
    column: int
    """Index of the Report Period's column among the year columns."""
    scale: int

    def value(self, i: int) -> int | None:
        """Row `i`'s figure in the Report Period's column, in base units."""
        values = _values(self.rows[i].cells)
        if len(values) not in (self.years, self.years + 1):
            return None
        figure = values[len(values) - self.years + self.column]
        return None if figure is None else int(figure * self.scale)

    def is_nil(self, i: int) -> bool:
        """Whether row `i` has a dash, not a figure, in the Report Period's column."""
        values = _values(self.rows[i].cells)
        if len(values) not in (self.years, self.years + 1):
            return False
        return values[len(values) - self.years + self.column] is None

    def fact(self, metric: str, i: int, segment: str | None = None) -> FinancialFact:
        filing = self.filing
        return FinancialFact(
            ticker=filing.ticker,
            report_period=filing.report_period,
            metric=metric,
            value=self.value(i),
            unit="USD",
            filing_id=filing.filing_id,
            period_months=12 if filing.form_type == "10-K" else 3,
            label=self.rows[i].label,
            scale=self.scale,
            offset=self.rows[i].offset,
            segment=segment,
        )


def _income_statement(filing: Filing) -> _Table | None:
    body = filing.body
    rows = _rows(body, filing.toc.end if filing.toc else 0)
    candidates = []
    for i in _revenue_rows(rows):
        header = _header_row(rows, i, len(_values(rows[i].cells)))
        if header is not None:
            candidates.append((_statement_rank(body, rows, header, i), i, header))
    for _, i, header in sorted(candidates):
        years = _years(rows[header])
        column = _column(years, filing.report_period)
        scale = _scale(body, rows, header, i)
        if column is None or scale is None:
            continue
        statement = _Table(filing, rows, i, len(years), column, scale)
        if statement.value(i) is not None:
            return statement
    return None


def _net_income_row(statement: _Table) -> int | None:
    """The income statement's net income row: attributable to the Company if stated.

    Searched below the revenue row to the end of its table. Per-share rows, rows for
    continuing or discontinued operations and rows attributable to noncontrolling
    interests are never net income.
    """
    rows = statement.rows
    found: list[tuple[int, int]] = []
    for i in range(statement.anchor + 1, len(rows)):
        if not rows[i].cells or i > statement.anchor + _STATEMENT_ROWS:
            break
        match = _NET_INCOME_ROW.fullmatch(_norm(rows[i].label))
        if match and statement.value(i) is not None:
            found.append((0 if match["attributable"] else 1, i))
    return min(found)[1] if found else None


def _segment_revenue(
    filing: Filing, rows: list[_Row], revenue: FinancialFact
) -> list[FinancialFact]:
    """Segment revenue from the first segment table whose segments reconcile to revenue.

    Segments are listed in one of two layouts:

    - as rows of figures directly above a row equal to total revenue (a subtotal
      replaces the rows it adds up), or
    - as heading rows, each followed by its own revenue row ("North America", then
      "Net sales"), with a "Consolidated" or "Total" heading left out.

    Either way the text that introduces them must call them segments, and they must
    add up to revenue. Reconciling rows (eliminations, hedging, corporate) count
    towards the sum but are not segments.
    """
    for table, start, end in _sub_tables(filing, rows):
        candidates = [
            *_listed_segments(table, start, end, revenue),
            _headed_segments(table, start, end),
        ]
        for intro, segments in candidates:
            if (
                len(segments) >= 2
                and _introduced_as_segments(rows, intro)
                and _reconciles([table.value(j) for _, j in segments], revenue, table)
            ):
                return [
                    table.fact("segment_revenue", j, segment=name)
                    for name, j in segments
                    if not _RECONCILING.search(name)
                ]
    return []


def _listed_segments(
    table: _Table, start: int, end: int, revenue: FinancialFact
) -> list[tuple[int, list[tuple[str, int]]]]:
    """For each row equal to revenue, the top level of the rows of figures above it.

    Each comes with the row its introduction ends on: the one above the first row.
    """
    rows = table.rows
    found = []
    for i in range(start, end):
        if table.value(i) != revenue.value:
            continue
        run = []
        j = i - 1
        while j > start and rows[j].label and (table.value(j) is not None or table.is_nil(j)):
            if not table.is_nil(j):  # a dash for the period: nil, neither segment nor sum
                run.insert(0, j)
            j -= 1
        if run:
            segments = [(_segment_name(rows[k].label), k) for k in _collapse_subtotals(run, table)]
            found.append((run[0] - 1, segments))
    return found


def _headed_segments(table: _Table, start: int, end: int) -> tuple[int, list[tuple[str, int]]]:
    """Each heading row paired with the first revenue row under it, and the first heading."""
    rows = table.rows
    segments: list[tuple[str, int]] = []
    first = start
    heading = None
    for i in range(start + 1, end):
        row = rows[i]
        if not _is_data(row):
            heading = (i, _segment_name(row.label)) if row.label else None
        elif heading and _REVENUE_LABEL.fullmatch(_norm(row.label)) and table.value(i) is not None:
            if not _TOTAL_HEADING.fullmatch(heading[1].lower()):
                if not segments:
                    first = heading[0]
                segments.append((heading[1], i))
            heading = None
    return first, segments


def _introduced_as_segments(rows: list[_Row], i: int) -> bool:
    """Whether the text ending at row `i` calls what follows segments.

    Read upwards from row `i` across label and header rows to the prose line above
    the table, stopping at a row of figures. Short texts are read whole; of a long one
    (a paragraph glued to the table's title) only the last sentence counts.
    """
    for j in range(i, max(-1, i - _INTRO_ROWS), -1):
        row = rows[j]
        if _is_data(row):
            return False
        text = " ".join((row.label, *row.cells)).strip()
        if len(text) > _SHORT_TEXT:
            text = _SENTENCE_BREAK.split(text.rstrip(" :|"))[-1][-_SHORT_TEXT * 2 :]
        if _SEGMENT.search(text):
            return True
        if not row.cells:
            return False
    return False


def _collapse_subtotals(run: list[int], table: _Table) -> list[int]:
    """The top level of a run of rows: a subtotal replaces the rows it adds up.

    A row is a subtotal when it equals the sum of two or more rows directly above it
    (UnitedHealth's "Optum" over Optum Health, Optum Insight, Optum Rx).
    """
    kept: list[int] = []
    for i in run:
        value = table.value(i)
        for n in range(len(kept), 1, -1):
            if sum(table.value(j) for j in kept[-n:]) == value:
                del kept[-n:]
                break
        kept.append(i)
    return kept


def _sub_tables(filing: Filing, rows: list[_Row]) -> list[tuple[_Table, int, int]]:
    """Every block of a table that starts at a header row, with its columns located.

    Runs of `|` rows are split at each header row (a row of years over the figures),
    since a page footer with a `|` can glue separate tables into one run.
    """
    blocks = []
    run_start = None
    for i, row in enumerate([*rows, _Row("", (), -1)]):
        if row.cells and run_start is None:
            run_start = i
        elif not row.cells and run_start is not None:
            headers = [j for j in range(run_start, i) if not _is_data(rows[j]) and _years(rows[j])]
            blocks += zip(headers, [*headers[1:], i][: len(headers)], strict=True)
            run_start = None
    tables = []
    for header, end in blocks:
        first = next((i for i in range(header + 1, end) if _is_data(rows[i])), None)
        if first is None or _header_row(rows, first, len(_values(rows[first].cells))) != header:
            continue
        years = _years(rows[header])
        column = _column(years, filing.report_period)
        scale = _scale(filing.body, rows, header, first)
        if column is not None and scale is not None:
            tables.append((_Table(filing, rows, first, len(years), column, scale), header, end))
    return tables


def _reconciles(values: list[int], revenue: FinancialFact, table: _Table) -> bool:
    """Whether segment figures add up to revenue, allowing for rounding of each figure."""
    return abs(sum(values) - revenue.value) < len(values) * table.scale


def _segment_name(label: str) -> str:
    return re.sub(r"\s+", " ", _FOOTNOTE.sub("", label.replace("\u00a0", " "))).strip(" :")


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
    negative = cell.lstrip("$ ").startswith(("(", "-"))
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
