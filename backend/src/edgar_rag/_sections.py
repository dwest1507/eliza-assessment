"""Section splitter, internal to the Corpus seam.

Splits a cleaned body into Sections at its Item headings. Each Form Type has a fixed
list of Items, each with its official title and the standard Section it maps to, so
10-K Item 7 and 10-Q Part I Item 2 are both MD&A.

Flattening glues headings into running text ("...otherwise stated.PART IItem 1.
BusinessCompany Background..."), so a heading is found by its Item number followed
by the start of its official title, not by its position on a line. The same words
also appear in cross-references ("see Part II, Item 7, “Management’s Discussion..."),
which are told apart by what comes just before them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from edgar_rag._body import Span

UNSECTIONED = "Unsectioned"


@dataclass(frozen=True)
class Section:
    """A part of a Filing's cleaned body: an Item, or text outside any Item."""

    name: str
    """The standard Section name (e.g. "MD&A"), or "Unsectioned" for text outside
    any recognised Item."""
    item: str | None
    """The Item label as the Form Type numbers it ("Item 7", "Part I, Item 2"), or
    None for unsectioned text."""
    span: Span
    """Where the Section sits in the cleaned body."""
    text: str = field(repr=False)


@dataclass(frozen=True)
class _Item:
    label: str
    number: str
    title: re.Pattern[str]
    section: str

    @property
    def required(self) -> bool:
        """Whether a Filing of this Form Type should have this Item. "Other" Items are
        optional, and Item 1C (Cybersecurity) only applies to fiscal years ending on or
        after 15 December 2023."""
        return self.section not in {"Other", "Cybersecurity"}


def _items(part: str | None, rows: list[tuple[str, str, str]]) -> list[_Item]:
    prefix = f"Part {part}, " if part else ""
    return [
        _Item(f"{prefix}Item {n}", n, re.compile(title.replace(" ", r"\s*"), re.I), section)
        for n, title, section in rows
    ]


# Titles are regexes matched case-insensitively, with any spaces optional.
_ITEMS: dict[str, list[_Item]] = {
    "10-K": _items(
        None,
        [
            ("1", "Business", "Business"),
            ("1A", "Risk Factors", "Risk Factors"),
            ("1B", "Unresolved Staff", "Other"),
            ("1C", "Cybersecurity", "Cybersecurity"),
            ("2", "Properties", "Other"),
            ("3", "Legal Proceedings", "Legal Proceedings"),
            ("4", r"(?:Mine Safety|Submission of Matters|\(?Removed and Reserved)", "Other"),
            ("5", "Market for", "Other"),
            ("6", r"(?:Selected|\[?Reserved)", "Other"),
            ("7", "Management.s Discussion", "MD&A"),
            ("7A", "Quantitative and Qualitative", "Market Risk"),
            ("8", "(?:Consolidated )?Financial Statements", "Financial Statements"),
            ("9", "Changes in and Disagreements", "Other"),
            ("9A", "Controls and Procedures", "Controls and Procedures"),
            ("9B", "Other Information", "Other"),
            ("9C", "Disclosure Regarding Foreign", "Other"),
            ("10", "Directors", "Other"),
            ("11", "Executive Compensation", "Other"),
            ("12", "Security Ownership", "Other"),
            ("13", "Certain Relationships", "Other"),
            ("14", "Principal Account", "Other"),
            ("15", "Exhibits?", "Other"),
            ("16", "Form 10-K Summary", "Other"),
        ],
    ),
    "10-Q": _items(
        "I",
        [
            ("1", "(?:Condensed )?(?:Consolidated )?Financial Statements", "Financial Statements"),
            ("2", "Management.s Discussion", "MD&A"),
            ("3", "Quantitative and Qualitative", "Market Risk"),
            ("4", "Controls and Procedures", "Controls and Procedures"),
        ],
    )
    + _items(
        "II",
        [
            ("1", "Legal Proceedings", "Legal Proceedings"),
            ("1A", "Risk Factors", "Risk Factors"),
            ("2", "Unregistered Sales", "Other"),
            ("3", "Defaults", "Other"),
            ("4", r"(?:Mine Safety|\(?Removed and Reserved|\[?Reserved)", "Other"),
            ("5", "Other Information", "Other"),
            ("6", "Exhibits?", "Other"),
        ],
    ),
}

# An Item number and the separator before its title: "Item 1A.", "ITEM\xa07 |", "Item 8:".
_ITEM_NUMBER = re.compile(r"Item\s*(\d{1,2})([A-C]?)\s*[.:\-–—]?[\s|]*", re.I)

# A cross-reference names an Item mid-sentence: after a lower-case word or a comma
# ("see Item 1A", "Part II, Item 7") or inside quotes (“Item 1A. Risk Factors”).
_CROSS_REFERENCE = re.compile(r"(?:[a-z,][ \xa0]+[“\"'‘]?|[“\"'‘])$")
# ...except when the lower-case word ends a "Table of Contents" running page header.
_RUNNING_HEADER = re.compile(r"Table of Contents[ \xa0]*$", re.I)
_LOOKBEHIND = 30

# A cross-reference index is a run of at least this many short table rows naming
# Items, each starting within a short distance of the next.
_MIN_INDEX_ROWS = 5
_MAX_ROW_CHARS = 250
_MAX_ROW_GAP = 250


def split_sections(
    text: str, form_type: str, search_from: int
) -> tuple[tuple[Section, ...], tuple[str, ...]]:
    """Split the cleaned body into Sections, looking for headings from `search_from`
    (the end of the table of contents) on. Every character lands in one Section.

    Also returns the required Sections that were not found, as "MD&A (Item 7)".
    """
    items = _ITEMS.get(form_type, [])
    starts = _find_headings(text, items, search_from)
    found = {item.label for _, item in starts}
    missing = tuple(
        f"{item.section} ({item.label})"
        for item in items
        if item.required and item.label not in found
    )
    return _partition(text, starts), missing


def _find_headings(text: str, items: list[_Item], search_from: int) -> list[tuple[int, _Item]]:
    """Each Item's heading position.

    First pass: take Items in form order, searching for each after the one before it,
    so a cross-reference early in the body cannot stand in for a later heading.
    Second pass: look for any Item still missing anywhere after the TOC, since some
    Filings reorder their Items (Bank of America's 10-Qs open with MD&A).
    """
    candidates = _drop_index_rows(text, _candidates(text, items, search_from))
    by_item: dict[str, list[int]] = {item.label: [] for item in items}
    for start, item in candidates:
        by_item[item.label].append(start)

    found: dict[str, tuple[int, _Item]] = {}
    pos = search_from
    for item in items:
        start = next((c for c in by_item[item.label] if c >= pos), None)
        if start is not None:
            found[item.label] = (start, item)
            pos = start + 1
    for item in items:
        if item.label not in found:
            taken = {start for start, _ in found.values()}
            start = next((c for c in by_item[item.label] if c not in taken), None)
            if start is not None:
                found[item.label] = (start, item)
    return list(found.values())


def _candidates(text: str, items: list[_Item], search_from: int) -> list[tuple[int, _Item]]:
    """Every place after `search_from` that looks like an Item heading, in body order:
    an Item number followed by that Item's title, not in a cross-reference."""
    by_number: dict[str, list[_Item]] = {}
    for item in items:
        by_number.setdefault(item.number.upper(), []).append(item)
    found = []
    for m in _ITEM_NUMBER.finditer(text, search_from):
        number = (m.group(1) + m.group(2)).upper()
        matching = [item for item in by_number.get(number, []) if item.title.match(text, m.end())]
        if not matching:
            continue
        before = text[max(0, m.start() - _LOOKBEHIND) : m.start()]
        if not _CROSS_REFERENCE.search(before) or _RUNNING_HEADER.search(before):
            found.append((m.start(), matching[0]))
    return found


def _drop_index_rows(text: str, candidates: list[tuple[int, _Item]]) -> list[tuple[int, _Item]]:
    """Drop runs of candidates that are rows of a cross-reference index.

    Some Filings (McDonald's, Intel, Mastercard) use their own headings and map them to
    Items in an index table: "Item 1A | Risk Factors | Page28". Each row is a short
    table line followed closely by the next row. A real heading is followed by its
    text, so it never sits in a run of such rows.
    """

    def is_row(i: int) -> bool:
        start = candidates[i][0]
        line_end = text.find("\n", start)
        line = text[start : line_end if line_end != -1 else len(text)]
        return "|" in line and len(line) < _MAX_ROW_CHARS

    def close_to_next(i: int) -> bool:
        return i + 1 < len(candidates) and candidates[i + 1][0] - candidates[i][0] < _MAX_ROW_GAP

    drop: set[int] = set()
    i = 0
    while i < len(candidates):
        j = i
        while j < len(candidates) and is_row(j) and close_to_next(j):
            j += 1
        if j - i >= _MIN_INDEX_ROWS:
            # The run's last row is not followed by another row, but is still a row.
            drop.update(range(i, j + 1 if j < len(candidates) and is_row(j) else j))
        i = j + 1
    return [c for k, c in enumerate(candidates) if k not in drop]


def _partition(text: str, starts: list[tuple[int, _Item]]) -> tuple[Section, ...]:
    starts = sorted(starts, key=lambda s: s[0])
    sections: list[Section] = []
    first = starts[0][0] if starts else len(text)
    if first > 0:
        sections.append(Section(UNSECTIONED, None, Span(0, first), text[:first]))
    for i, (start, item) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        sections.append(Section(item.section, item.label, Span(start, end), text[start:end]))
    return tuple(sections)
