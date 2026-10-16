"""Chunker, internal to the retrieval seam.

Turns one Filing into the chunks the index holds. Every chunk sits inside one Section
and carries the Filing's metadata. Before chunking, each Section's text is cleaned of
what should never reach an Answer Call (findings 8–10):

- the table of contents, which repeats every Item heading;
- exhibit-index rows ("31.1 | Certification of ...") and the signature block;
- page furniture: "Table of Contents" running headers, page footers such as
  "Apple Inc. | 2024 Form 10-K | 21", and lines holding only a page number.

The cleaned text is then split into table blocks (runs of `|`-separated rows) and prose.
Prose is split on sentence boundaries into chunks of about 500–800 tokens, each opening
with the last sentence or two of the chunk before it. A table is kept whole when it fits,
else split into row groups that each repeat the table's header rows. A short line of
prose just before a table (its caption, "dollars in millions") goes into the table's
chunks. A 10-Q Risk Factors Section that is too short to hold risk text only points
elsewhere ("no material changes"), so it becomes one chunk of kind `risk_pointer`
(finding 16).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from edgar_rag.corpus import Filing, Section

ChunkKind = Literal["prose", "table", "risk_pointer"]

TARGET_TOKENS = 600
MAX_TOKENS = 800
OVERLAP_TOKENS = 60

# Finding 16: every 10-Q Risk Factors pointer is under 2,500 characters, every Section
# stating risk text above it.
_RISK_POINTER_MAX_CHARS = 2_500
# A `|`-separated line is a table row only if no cell is longer than this: some Filings
# glue whole pages of prose into one line around a page footer.
_MAX_TABLE_CELL = 500
# Prose shorter than this just before a table is read as the table's caption.
_CAPTION_MAX_TOKENS = 60
# A table keeps at most this many leading rows as the header its row groups repeat.
_MAX_HEADER_ROWS = 3
# A chunk with fewer word characters than this carries nothing worth retrieving.
_MIN_WORD_CHARS = 20


@dataclass(frozen=True)
class Chunk:
    """One indexed piece of a Filing, inside one Section."""

    filing_id: str
    ticker: str
    company: str
    sector: str | None
    industry: str | None
    form_type: str
    report_period: str
    fiscal_period: str | None
    coverage: str | None
    section: str
    item: str | None
    kind: ChunkKind
    ordinal: int
    """Position of the chunk within its Filing, in body order."""
    text: str


def count_tokens(text: str) -> int:
    """Approximate token count: about four characters per token.

    A stand-in that keeps the core package on the standard library. It matches the EDA's
    o200k_base measure of the Corpus closely enough to size chunks and budgets; the
    evaluation re-measures with the chosen model's tokenizer (finding 15).
    """
    return math.ceil(len(text) / 4)


def chunk_filing(filing: Filing) -> list[Chunk]:
    """Every chunk of one Filing, in body order. Chunks never cross a Section boundary."""
    chunks: list[Chunk] = []
    for section in filing.sections:
        text = _clean(_without_toc(section, filing))
        if not text.strip():
            continue
        if _is_risk_pointer(filing, section, text):
            pieces: list[tuple[ChunkKind, str]] = [("risk_pointer", text.strip())]
        else:
            pieces = list(_split(text))
        for kind, piece in pieces:
            if len(re.findall(r"\w", piece)) < _MIN_WORD_CHARS:
                continue
            chunks.append(
                Chunk(
                    filing_id=filing.filing_id,
                    ticker=filing.ticker,
                    company=filing.company,
                    sector=filing.sector,
                    industry=filing.industry,
                    form_type=filing.form_type,
                    report_period=filing.report_period.isoformat(),
                    fiscal_period=filing.fiscal_period,
                    coverage=filing.coverage,
                    section=section.name,
                    item=section.item,
                    kind=kind,
                    ordinal=len(chunks),
                    text=piece,
                )
            )
    return chunks


def _is_risk_pointer(filing: Filing, section: Section, text: str) -> bool:
    return (
        filing.form_type == "10-Q"
        and section.name == "Risk Factors"
        and len(text.strip()) < _RISK_POINTER_MAX_CHARS
    )


def _without_toc(section: Section, filing: Filing) -> str:
    """The Section's text with any part of the table of contents cut out."""
    toc = filing.toc
    if toc is None or toc.end <= section.span.start or toc.start >= section.span.end:
        return section.text
    start = max(toc.start, section.span.start) - section.span.start
    end = min(toc.end, section.span.end) - section.span.start
    return section.text[:start] + section.text[end:]


# --- Cleaning -------------------------------------------------------------------------

# An exhibit-index row: an exhibit number in the first cell ("31.1 |", "10.12(22) |",
# "101 |", "4.2* |"), as in the EDA's text anatomy.
_EXHIBIT_ROW = re.compile(
    r"^\s*\|?\s*(?:\d{1,3}(?:\.[0-9A-Z]{1,4}){1,2}(?:\(\d+\))?|10[14])\s*[*†‡#+^]*\s*"
    r"(?:\(\w\))?\s*\|"
)
_EXHIBIT_HEADER = re.compile(r"^\s*\|?\s*Exhibit\s*(?:Number|No\.?)?\s*\|", re.I)

# The signature block opens with "Pursuant to the requirements of ... the registrant has
# duly caused this report to be signed", sometimes after a "SIGNATURES" heading. Many
# 10-Ks add a second one for the directors: "this report has been signed below by the
# following persons".
_SIGNATURE_SENTENCE = re.compile(
    r"duly\s+caused\s+this\s+.{0,40}?to\s+be\s+signed"
    r"|has\s+been\s+signed\s+(?:below\s+)?by\s+the\s+following\s+persons",
    re.I,
)
_SIGNATURE_OPENING = re.compile(r"(?:SIGNATURES?\s*)?Pursuant\s+to\s+the\s+requirements", re.I)
_SIGNATURE_HEADING = re.compile(r"SIGNATURES?", re.I)
_SIGNATURE_LOOKBACK = 400
# The block's signature rows are short; the first long line after it is real text again.
_SIGNATURE_ROW_MAX_CHARS = 300

_RUNNING_HEADER = re.compile(r"Table\s+of\s+Contents", re.I)
# Page footers: "Apple Inc. | 2024 Form 10-K | 21", "Apple Inc. | Q3 2024 Form 10-Q | 21",
# "TARGET CORPORATION |  | 2024 Form 10-K | 1", "Comcast 2025 Annual Report on Form 10-K
# | 2 |", "328 |  | JPMorgan Chase & Co./2025 Form 10-K". The first kind must start a line
# or follow a sentence, so it never swallows the prose glued in front of it.
_PAGE_FOOTER = re.compile(
    r"(?:(?<=[.!?:;)\]”\"\d\n])|(?<=[.!?] )|^)"
    r"(?:[A-Z][\w.,&'’ ]{0,60}?\s*\|\s*(?:\|\s*)?)?"
    r"(?:(?:Fiscal|Annual|Report|on|Q[1-4]|\d{4}|[A-Z][a-z]+)\s+){0,5}"
    r"Form\s+10-[KQ]\s*\|\s*\d{1,3}(?![\d./-])(?:\s*\|)?"
    r"|\d{1,3}\s*\|\s*\|?\s*[A-Z][\w.,&'’ ]{1,60}?/\d{4}\s+Form\s+10-[KQ]",
    re.M,
)
# A line holding only a page number ("23", "- 23 -", "Page 23", "F-12").
_PAGE_NUMBER_LINE = re.compile(r"\s*(?:-\s*)?(?:Page\s*)?(?:[A-Z]-)?\d{1,3}(?:\s*-)?\s*", re.I)
# A page number glued on after a sentence: at the end of a line ("...agreements. 24") or
# before the next sentence ("...these functions.20Any unauthorized...").
_TRAILING_PAGE_NUMBER = re.compile(r"(?<=[.!?:”)])\s+\d{1,3}$", re.M)
_GLUED_PAGE_NUMBER = re.compile(r"(?<=[a-z][.!?])\d{1,3}(?=[A-Z][a-z])")
# A line left holding only table separators once its furniture is gone.
_EMPTY_ROW = re.compile(r"[\s|]*")


def _clean(text: str) -> str:
    text = _without_signatures(text)
    text = _RUNNING_HEADER.sub("", text)
    text = _PAGE_FOOTER.sub("", text)
    text = _TRAILING_PAGE_NUMBER.sub("", text)
    text = _GLUED_PAGE_NUMBER.sub("", text)
    lines = [
        line
        for line in text.split("\n")
        if not (
            _EXHIBIT_ROW.match(line)
            or _EXHIBIT_HEADER.match(line)
            or _PAGE_NUMBER_LINE.fullmatch(line)
            or _EMPTY_ROW.fullmatch(line)
        )
    ]
    return "\n".join(lines)


def _without_signatures(text: str) -> str:
    """Cut every signature block: from its opening sentence (and any "SIGNATURES"
    heading just before it) to the first long line after it."""
    while match := _SIGNATURE_SENTENCE.search(text):
        window_start = max(0, match.start() - _SIGNATURE_LOOKBACK)
        openings = list(_SIGNATURE_OPENING.finditer(text, window_start, match.start()))
        start = openings[-1].start() if openings else match.start()
        line_start = text.rfind("\n", 0, start) + 1
        if not text[line_start:start].strip():
            start = line_start
            # A "SIGNATURES" heading on the line before belongs to the block.
            previous_start = text.rfind("\n", 0, max(line_start - 1, 0)) + 1
            if line_start and _SIGNATURE_HEADING.fullmatch(
                text[previous_start : line_start - 1].strip()
            ):
                start = previous_start
        end = text.find("\n", match.end())
        while end != -1:
            next_end = text.find("\n", end + 1)
            line = text[end + 1 : next_end if next_end != -1 else len(text)]
            if len(line) > _SIGNATURE_ROW_MAX_CHARS and not _SIGNATURE_SENTENCE.search(line):
                break
            end = next_end
        text = text[:start] + ("" if end == -1 else text[end:])
    return text


# --- Splitting ------------------------------------------------------------------------


def _is_table_row(line: str) -> bool:
    return "|" in line and max(len(cell) for cell in line.split("|")) <= _MAX_TABLE_CELL


def _blocks(text: str) -> Iterator[tuple[bool, list[str]]]:
    """Runs of consecutive table rows or prose lines, as (is_table, lines)."""
    current: list[str] = []
    current_is_table = False
    for line in text.split("\n"):
        is_table = _is_table_row(line)
        if current and is_table != current_is_table:
            yield current_is_table, current
            current = []
        current_is_table = is_table
        current.append(line)
    if current:
        yield current_is_table, current


def _split(text: str) -> Iterator[tuple[ChunkKind, str]]:
    held: str | None = None  # a short prose block, kept back as the next table's caption
    caption: str | None = None  # the line of prose just before the next table
    for is_table, lines in _blocks(text):
        block = "\n".join(lines)
        if is_table:
            for rows in _row_groups(lines, caption):
                yield "table", "\n".join(rows)
            held = caption = None
            continue
        if held is not None:
            yield from (("prose", piece) for piece in _prose_chunks(held))
        if count_tokens(block) <= _CAPTION_MAX_TOKENS:
            held = caption = block
            continue
        yield from (("prose", piece) for piece in _prose_chunks(block))
        last = _sentences(block)[-1].strip()
        held = None
        caption = last if count_tokens(last) <= _CAPTION_MAX_TOKENS else None
    if held is not None:
        yield from (("prose", piece) for piece in _prose_chunks(held))


def _row_groups(rows: list[str], caption: str | None) -> Iterator[list[str]]:
    """A table whole, or as row groups that each repeat the header rows."""
    lead = [caption] if caption else []
    if count_tokens("\n".join(lead + rows)) <= MAX_TOKENS:
        yield lead + rows
        return
    header_count = _header_rows(rows)
    header = lead + rows[:header_count]
    if count_tokens("\n".join(header)) > MAX_TOKENS // 2:
        header = []
    group: list[str] = []
    for row in rows[header_count:] if header else rows:
        if group and count_tokens("\n".join(header + group + [row])) > TARGET_TOKENS:
            yield header + group
            group = []
        group.append(row)
    if group:
        yield header + group


_NUMBER_CELL = re.compile(r"\(?\$?\s*-?\d[\d,]*(?:\.\d+)?\)?\s*%?")
_YEAR = re.compile(r"(?:19|20)\d{2}")


def _header_rows(rows: list[str]) -> int:
    """How many leading rows are the table's header: those before the first row with a
    label and a figure that is not a year."""
    for i, row in enumerate(rows[:_MAX_HEADER_ROWS]):
        cells = [c.strip() for c in row.split("|")]
        has_label = bool(cells[0]) and not _NUMBER_CELL.fullmatch(cells[0])
        figures = [c for c in cells[1:] if c and _NUMBER_CELL.fullmatch(c)]
        if has_label and any(not _YEAR.fullmatch(f) for f in figures):
            return i
    return min(len(rows) - 1, _MAX_HEADER_ROWS)


# A sentence ends at ., ! or ? (and any closing quote or bracket) followed by whitespace,
# or glued straight onto the next sentence's capital letter ("...affected.Because").
_SENTENCE_END = re.compile(r"(?<=[a-z0-9)%][.!?])[\"”’)]?(?:\s+|(?=[A-Z]))|\n+")


def _sentences(text: str) -> list[str]:
    pieces, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        pieces.append(text[start : m.end()])
        start = m.end()
    pieces.append(text[start:])
    sentences: list[str] = []
    for piece in pieces:
        if not piece.strip():
            continue
        # A "sentence" longer than a chunk (a glued heading run, a list) is cut on words.
        while count_tokens(piece) > MAX_TOKENS:
            cut = piece.rfind(" ", 0, MAX_TOKENS * 4)
            cut = cut if cut > 0 else MAX_TOKENS * 4
            sentences.append(piece[:cut])
            piece = piece[cut:]
        sentences.append(piece)
    return sentences


def _prose_chunks(text: str) -> list[str]:
    """Sentences packed into chunks of about TARGET_TOKENS, never above MAX_TOKENS, each
    opening with up to OVERLAP_TOKENS of the chunk before it."""
    chunks: list[str] = []
    current: list[str] = []
    fresh = False  # whether `current` holds anything beyond the carried-over overlap
    for sentence in _sentences(text):
        if fresh and count_tokens("".join(current + [sentence])) > MAX_TOKENS:
            chunks.append("".join(current).strip())
            current, fresh = _overlap(current), False
        if count_tokens("".join(current + [sentence])) > MAX_TOKENS:
            current = []
        current.append(sentence)
        fresh = True
        if count_tokens("".join(current)) >= TARGET_TOKENS:
            chunks.append("".join(current).strip())
            current, fresh = _overlap(current), False
    if fresh:
        chunks.append("".join(current).strip())
    return chunks


def _overlap(sentences: list[str]) -> list[str]:
    """The end of a chunk to open the next one with: its last sentences that fit in
    OVERLAP_TOKENS, or, when its last sentence alone is longer, that sentence's last
    words."""
    kept: list[str] = []
    for sentence in reversed(sentences):
        if count_tokens("".join([sentence] + kept)) > OVERLAP_TOKENS:
            break
        kept.insert(0, sentence)
    if kept or not sentences:
        return kept
    last = sentences[-1]
    cut = last.find(" ", len(last) - OVERLAP_TOKENS * 4)
    return [last[cut + 1 :]] if cut != -1 else []
