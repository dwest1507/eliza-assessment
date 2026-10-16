"""Body cleaner, internal to the Corpus seam.

Two jobs:

- **Strip the XBRL noise.** Every Filing body opens with machine-readable XBRL
  residue (context IDs, taxonomy URLs, hidden facts) glued in front of the SEC
  cover page. The cover page always starts with "UNITED STATES SECURITIES AND
  EXCHANGE COMMISSION", so everything before that phrase is noise.
- **Locate the table of contents.** TOC rows repeat the real Item headings
  ("Item 1A. | Risk Factors | 5"), so Section detection must skip them. The TOC
  is the first run of rows that look like "heading | page number" and name
  enough distinct Items or standard headings. Its layout varies a lot between
  Companies (page number first or last, Item number in its own column, page
  references like "K-24" or "Pages37-51"), so the rules below are deliberately
  loose about cell order and strict about what counts as a heading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Whitespace inside the phrase is optional: the flattening often glues words together.
_COVER_PAGE = re.compile(r"UNITED\s*STATES\s*SECURITIES\s*AND\s*EXCHANGE\s*COMMISSION", re.I)

# A page reference cell: "5", "9-31", "K-24", "Pages37-51", "Page2", "N/A", "None".
# Any of them may carry a footnote marker: "Not Applicable(a)", "Page52(a)".
_PAGE_REF = re.compile(
    r"(?:(?:Pages?\s*)?(?:[A-Z]{1,2}-?)?\d{1,3}(?:\s*[-–]\s*(?:[A-Z]{1,2}-?)?\d{1,3})?"
    r"|Pages?(?:\s*No\.)?|N/?A|None|Not applicable)(?:\s*\([a-z0-9]\))*",
    re.I,
)
# A cell that only labels the TOC's layout: "Page", "Item", "Part II", "PART I. FINANCIAL ...".
_LABEL_CELL = re.compile(r"Items?|Pages?(?:\s*No\.)?|Part\s*[IV]{1,3}\b.{0,60}", re.I)
# A cell holding only an Item label: "Item 1A.", "Item 7", or a bare "1A." / "7".
_ITEM_LABEL = re.compile(r"(?:Item\s*)?\d{1,2}[A-C]?\.?", re.I)
# A cell that starts with an Item label: "Item 1A. Risk Factors".
_ITEM_PREFIX = re.compile(r"Item\s*(\d{1,2}[A-C]?)\b", re.I)
# A cell that starts with a standard 10-K / 10-Q heading.
_HEADING_CELL = re.compile(
    r"(?:Business|Risk Factors|Unresolved Staff|Cybersecurity|Properties|Legal Proceedings"
    r"|Mine Safety|Market for|Management.s Discussion|Quantitative and Qualitative"
    r"|Financial Statements|Changes in and Disagreements|Controls and Procedures"
    r"|Other Information|Directors|Executive Compensation|Security Ownership"
    r"|Certain Relationships|Principal Account|Exhibits?|Form 10-K Summary|Signatures?)\b",
    re.I,
)

_MAX_ROW_CHARS = 250
_MAX_CELLS = 4
_MAX_GAP_LINES = 3
_MIN_HEADING_ROWS = 5
_MIN_DISTINCT_HEADINGS = 3


@dataclass(frozen=True)
class Span:
    """A character range [start, end) in a Filing's cleaned body."""

    start: int
    end: int


@dataclass(frozen=True)
class CleanedBody:
    text: str
    xbrl_noise_chars: int
    toc: Span | None


def clean_body(raw: str) -> CleanedBody:
    cover = _COVER_PAGE.search(raw)
    start = cover.start() if cover else 0
    text = raw[start:]
    return CleanedBody(text=text, xbrl_noise_chars=start, toc=_find_toc(text))


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.split("|") if c.strip()]


def _is_toc_row(line: str) -> bool:
    if len(line) > _MAX_ROW_CHARS:
        return False
    cells = _cells(line)
    if cells and all(_LABEL_CELL.fullmatch(c) or _ITEM_LABEL.fullmatch(c) for c in cells):
        return True
    if not 2 <= len(cells) <= _MAX_CELLS:
        return False
    return bool(_PAGE_REF.fullmatch(cells[-1]) or _PAGE_REF.fullmatch(cells[0]))


def _heading_of(line: str) -> str | None:
    """The Item or standard heading a TOC row names, normalised, or None."""
    cells = _cells(line)
    if len(cells) < 2:
        return None  # a lone "Item 1" or "Part II" is a label, in the TOC or the body
    for cell in cells:
        if m := _ITEM_PREFIX.match(cell):
            return m.group(1).upper()
    for cell in cells:
        if m := _HEADING_CELL.match(cell):
            return m.group(0).lower()
    # A bare Item number in its own column ("1A. | Risk Factors | 22"): only in the
    # first cell of a row that ends in a page reference, since a bare number
    # anywhere else is a page reference or a page footer.
    if _ITEM_LABEL.fullmatch(cells[0]) and _PAGE_REF.fullmatch(cells[-1]):
        return cells[0].rstrip(".").upper()
    return None


def _find_toc(text: str) -> Span | None:
    """The first block of TOC rows that names enough distinct headings.

    A block is a run of TOC rows with gaps of at most a few other lines. It ends at
    its last row that names a heading, so a table that happens to follow the TOC
    is not swallowed.
    """
    lines = text.split("\n")
    first: int | None = None
    last_heading = 0
    headings: list[str] = []
    gap = 0
    # Blank padding closes a block that runs to the end of the body.
    for i, line in enumerate(lines + [""] * (_MAX_GAP_LINES + 1)):
        if _is_toc_row(line):
            gap = 0
            if first is None:
                first, headings = i, []
            if heading := _heading_of(line):
                last_heading = i
                headings.append(heading)
        elif first is not None:
            gap += 1
            if gap > _MAX_GAP_LINES:
                if _qualifies(headings):
                    start = sum(len(row) + 1 for row in lines[:first])
                    end = sum(len(row) + 1 for row in lines[: last_heading + 1]) - 1
                    return Span(start, end)
                first = None
    return None


def _qualifies(headings: list[str]) -> bool:
    return len(headings) >= _MIN_HEADING_ROWS and len(set(headings)) >= _MIN_DISTINCT_HEADINGS
