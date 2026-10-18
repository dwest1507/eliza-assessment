"""The generation harness's checks in code: citations, figures, Coverage Gaps and structure.

Pure functions over an answer's Markdown text, so each is unit-tested on hand-written
answers. An answer is read as a list of units (`units`): each prose paragraph, each
list item and each table body row is one unit, since each makes its own claims.
Headings, table header rows, lead-ins that end with a colon, lines that are bold text
only, and the closing "Coverage" note are units too, but exempt from the citation rule:
they introduce claims or say what the Sources could not answer, so there is nothing
for them to cite.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import cache

from edgar_rag.golden_set import CoverageGapLabel
from edgar_rag.retrieval import load_missing_companies

__all__ = [
    "CitationCheck",
    "Claim",
    "CoverageGapCheck",
    "Figure",
    "FigureCheck",
    "StructureCheck",
    "Unit",
    "check_citations",
    "check_coverage_gaps",
    "check_figures",
    "check_structure",
    "claims",
    "figures",
    "source_numbers_cited",
    "units",
]

# One bracket of Source tags: [S1], [S1, S2], [S1; S2], [S1,S2 and S3], [S1–S5].
_TAG_BRACKET = re.compile(r"\[\s*S\d+(?:\s*(?:,|;|and|&|[-–—])\s*S?\d+)*\s*\]")
_TAG = re.compile(r"S?(\d+)(?:\s*[-–—]\s*S?(\d+))?")
_HEADING = re.compile(r"^#{1,6}\s")
_RULE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?$")
_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_BOLD_ONLY = re.compile(r"^(?:\*\*|__)[^*_]+(?:\*\*|__):?$")
_COVERAGE = re.compile(r"^(?:#{1,6}\s*|\*\*|__)?\s*coverage\b", re.I)
# A Coverage note that opens after another sentence: "... [S2]. **Coverage:** The ..."
_COVERAGE_IN_LINE = re.compile(r"[.!?\]]\s+(?:\*\*|__)?coverage\b[^.:]{0,20}:", re.I)
# What an uncited sentence may say without breaking a rule. Three rules read it, and
# they differ on purpose, so all three are described here:
#
# - `_ABSENCE`, the citation check's (`check_citations`): a unit whose every sentence
#   matches says what the Sources lack, so it need not cite. It is broad, and also
#   matches some plain statements about a Company ("Tesla has no exposure to ...").
# - `_GAP_MARKERS` (below, with the Coverage Gap check), `check_coverage_gaps`': what a
#   sentence stating each kind of Coverage Gap says, in any reasonable wording. Broad on
#   purpose, since a stated gap must not be missed.
# - The claim exemption (`claims`, `_states_gap`), narrowed in issue #89 to what #43 and
#   #52 decided: an uncited sentence is not a claim only when it is a fixed Coverage
#   Gap wording (`_FIXED_WORDING`), says what the Sources, Filings or Corpus lack,
#   naming them (`_RECORDS_LACK`), or matches a `_GAP_MARKERS` pattern and either
#   speaks of the Sources, Filings or Corpus (`_RECORDS`; for "periods differ", also
#   of the Filings' periods, `_FILING_PERIODS`) or names a Company missing from the
#   Corpus. Any other uncited sentence about a Company is a claim, however it reads.
#
# A sentence that says what the Sources lack, which has nothing to cite.
_ABSENCE = re.compile(
    r"\b(?:sources|filings|excerpts|materials|corpus)\b[^.;]{0,40}"
    r"(?:\bdo(?:es)? not\b|n['’]t\b|\black)"
    r"|\b(?:contains?|includes?|provides?|has|have)\s+no\b"
    r"|\b(?:no|not)\b[^.;]{0,60}"
    r"\b(?:sources?|filings?|excerpts?|corpus|evidence|provided|supplied|available)\b"
    r"|\bcan(?:not|['’]t)\s+(?:determine|assess|identify|compare|answer|tell)"
    r"|\bnot evidence\b",
    re.I,
)
_RECORDS_WORD = (
    r"(?:\b(?:sources?|filings?|excerpts?|corpus|dataset|10-[KQ]s?|financial facts"
    r"|snapshot compan(?:y|ies))|(?<!raw )\bmaterials)\b(?!\s+of\b)"
)
"""The Sources, Filings, Corpus or Financial Facts by any name, and the Corpus's
coverage class, but not "sources of revenue", "the filing of a lawsuit" or "raw
materials"."""
_RECORDS = re.compile(_RECORDS_WORD, re.I)
_WORDS = r"(?:[\w’'&-]+\s+){0,3}?"
_RECORDS_LACK = re.compile(
    # "The Sources do not include ...", "The Corpus lacks ...", "Based on the materials
    # provided, I cannot ...": the records open the sentence or a clause, so "findings
    # that Target's excerpt does not mention" stays a claim about Walmart.
    rf"(?:^\W*|[;:—–]\s*|,\s*(?:so|therefore|but)\s+){_WORDS}{_RECORDS_WORD}[^.;]{{0,40}}"
    r"(?:\bdo(?:es)?\s+not\b|n['’]t\b|\bcannot\b|\black|\bomit|\bsilent\b|\bsay nothing\b"
    r"|\b(?:contains?|includes?|provides?|gives?|has|have|holds?|offers?|shows?)\s+no\b)"
    # "... is not in the Filings provided", "Nothing in the excerpts ...", "... cannot be
    # assessed from the Sources", "... would not rest on the filings"
    r"|(?:\bno\b|\bnot\b|\bnothing\b|\bneither\b|\bnor\b|\bwithout\b|\bcannot\b"
    r"|n['’]t\b|\bunable\b|\babsent\b|\bmissing\b|\bunavailable\b)[^.;]{0,60}"
    rf"\b(?:in|from|among|within|across|on)\s+{_WORDS}{_RECORDS_WORD}"
    # "No usable Sources were found", "There are no Honeywell filings"
    rf"|\bno\s+{_WORDS}{_RECORDS_WORD}",
    re.I,
)
"""A sentence that says what the Sources, Filings or Corpus lack, naming them: the claim
exemption's absence rule, narrower than the citation check's `_ABSENCE`."""
_FIXED_WORDING = re.compile(
    r"^\W*(?:trend unavailable|not in the corpus|stale filing|no guidance in the filings"
    r"|periods differ)\b"
    r"|\bthis answer does not cover\b|\bleft out of this answer\b|\bso this answer covers\b"
    r"|\bcited here only as\b|\bthe outlook below is drawn from\b"
    r"|\bthe comparison is not of the same period\b",
    re.I,
)
"""The fixed Coverage Gap wordings (`edgar_rag._coverage`): a sentence opening with a
gap's label, or one of their own phrases, in case an answer splits a wording in two
("... 10-K for 2014. It does not describe General Electric today, so it is left out of
this answer.")."""
_FILING_PERIODS = re.compile(
    r"\breport(?:ing)?\s+periods?\b|\bthe\s+periods\b|\bsame[- ]period\b", re.I
)
"""The Filings' periods, as a "periods differ" sentence speaks of them; "fiscal years"
are the Companies'."""
_TAG_RUN = re.compile(rf"(?:{_TAG_BRACKET.pattern}\s*)+")


@dataclass(frozen=True)
class Unit:
    """One paragraph, list item or table row of an answer."""

    text: str
    tags: tuple[str, ...]
    """The Source tags it cites, as written ("S3"), in order of first citation."""
    exempt: bool
    """True for a unit that need not cite: a heading, a table header, a lead-in, a
    bold label, or anything in the closing Coverage note."""
    lead_in: bool = False
    """True for a paragraph exempt only because it ends with a colon: its sentences
    before the colon still make claims."""
    heading: str = ""
    """The nearest heading or bold label above the unit, without its markup or tags;
    empty above the first."""
    table_header: str = ""
    """For a table row after the first, the table's header row without its tags."""


@dataclass(frozen=True)
class CitationCheck:
    unknown_tags: tuple[str, ...]
    """Tags cited that are not among this turn's Sources."""
    uncited: tuple[str, ...]
    """Units that should cite a Source and cite none."""

    @property
    def passed(self) -> bool:
        return not self.unknown_tags and not self.uncited


def tags_in(text: str) -> tuple[str, ...]:
    """Every Source tag cited in the text, in order of first citation."""
    found: dict[str, None] = {}
    for bracket in _TAG_BRACKET.finditer(text):
        for first, last in _TAG.findall(bracket.group()[1:-1]):
            for number in range(int(first), int(last or first) + 1):
                found.setdefault(f"S{number}")
    return tuple(found)


def strip_tags(text: str) -> str:
    """The text without its Source tags."""
    text = re.sub(r"\s+([.,;:])", r"\1", _TAG_BRACKET.sub("", text))
    return re.sub(r"\s{2,}", " ", text).strip()


def units(answer: str) -> list[Unit]:
    """The answer's paragraphs, list items and table rows, in order."""
    result: list[Unit] = []
    in_coverage = False
    paragraph: list[str] = []
    table_rows = 0
    heading = header = ""

    def flush() -> None:
        nonlocal heading
        if paragraph:
            text = " ".join(paragraph)
            lead_in = not in_coverage and _is_lead_in(text)
            unit = _unit(text, in_coverage or lead_in, heading, lead_in)
            result.append(unit)
            if _BOLD_ONLY.match(text):
                heading = _heading_text(text)  # a bold label heads what follows
            paragraph.clear()

    for raw in answer.splitlines():
        line = raw.strip()
        if line.startswith("|"):
            flush()
            if _TABLE_SEPARATOR.match(line):
                continue
            table_rows += 1
            # The first row of a table is its header; a separator row follows it.
            if table_rows == 1:
                header = strip_tags(line)
                result.append(_unit(line, True, heading))
            else:
                result.append(_unit(line, in_coverage, heading, table_header=header))
            continue
        table_rows = 0
        if not line or _RULE.match(line):
            flush()
            continue
        if _HEADING.match(line):
            flush()
            in_coverage = bool(_COVERAGE.match(line))
            result.append(_unit(line, True, heading))
            heading = _heading_text(line)
            continue
        if _LIST_ITEM.match(line):
            flush()
            paragraph.append(_LIST_ITEM.sub("", line))
            flush()
            continue
        if not paragraph and _COVERAGE.match(line):
            in_coverage = True
        paragraph.append(line)
        if _COVERAGE_IN_LINE.search(line):
            # The claims before the note stay in this unit; what follows is the note.
            flush()
            in_coverage = True
    flush()
    return result


def _unit(
    text: str, exempt: bool, heading: str, lead_in: bool = False, table_header: str = ""
) -> Unit:
    bold = bool(_BOLD_ONLY.match(text))
    return Unit(
        text=text,
        tags=tags_in(text),
        exempt=exempt or bold,
        lead_in=lead_in and not bold,
        heading=heading,
        table_header=table_header,
    )


def _heading_text(line: str) -> str:
    """A heading or bold label as context for what follows: "## Apple's risks [S1]" is
    "Apple's risks"."""
    return strip_tags(re.sub(r"^#{1,6}\s+", "", line).strip("*_: ").strip())


def _is_lead_in(text: str) -> bool:
    return text.endswith(":") and not tags_in(text)


def check_citations(answer: str, source_numbers: Collection[int]) -> CitationCheck:
    """Every `[Sn]` tag names one of this turn's Sources, and every unit that is not
    exempt cites at least one."""
    valid = {f"S{n}" for n in source_numbers}
    unknown: dict[str, None] = {}
    uncited: list[str] = []
    for unit in units(answer):
        for tag in unit.tags:
            if tag not in valid:
                unknown.setdefault(tag)
        if not unit.tags and not unit.exempt and not _states_absence(unit.text):
            uncited.append(unit.text)
    return CitationCheck(unknown_tags=tuple(unknown), uncited=tuple(uncited))


def _states_absence(text: str) -> bool:
    """Whether every sentence of the unit says what the Sources lack (or opens the
    Coverage note): a statement of absence has nothing to cite."""
    cells = [c.strip() for c in text.strip("|").split("|")] if text.startswith("|") else [text]
    # In a table row, the cells after the first (the row's label) carry the statement.
    body = " ".join(cells[1:] if len(cells) > 1 else cells)
    return all(_ABSENCE.search(s) or _COVERAGE.match(s) for s in _sentences(body))


def source_numbers_cited(answer: str) -> set[int]:
    """The numbers of every Source the answer cites."""
    return {int(tag[1:]) for tag in tags_in(answer)}


# --- Figure exactness -------------------------------------------------------------------

_SCALES = {
    "thousand": 10**3,
    "k": 10**3,
    "million": 10**6,
    "mn": 10**6,
    "m": 10**6,
    "billion": 10**9,
    "bn": 10**9,
    "b": 10**9,
    "trillion": 10**12,
    "t": 10**12,
}

_FIGURE = re.compile(
    r"""
    (?<![\w.\-/])                                    # not part of a word, id or date
    (?P<currency>\$|US\$)?
    (?P<whole>\d{1,3}(?:,\d{3})+|\d+)(?P<fraction>\.\d+)?
    (?:\s?(?P<percent>%|percent\b|per\s?cent\b))?
    (?:\s?(?P<word>trillion|billion|million|thousand)\b|(?P<short>bn|mn|[TBMKtbmk])\b)?
    (?![\w\-])
    """,
    re.X,
)
_PASSAGE_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_NOT_A_FIGURE_BEFORE = re.compile(
    r"(?:\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
    r"|\b(?:Item|Items|Part|Note|Notes|Section|Rule)|\bS\d+,?)\s*$",
    re.I,
)
# The scale factors a passage number may be read at: "416,161" in a table "in
# millions" is $416.161 billion.
_RESCALE = tuple(Decimal(1000) ** k for k in range(-4, 5))
_FACT_SCALES = (1, 10**3, 10**6, 10**9, 10**12)


@dataclass(frozen=True)
class Figure:
    """A number an answer states as a figure: an amount, a percentage or a count."""

    text: str
    """As written, e.g. "$46.7 billion"."""
    mantissa: Decimal
    """The number as written, without sign or scale: 46.7."""
    decimals: int
    scale: int | None
    """The scale word's multiplier (10**9 for "billion"), or None if there is none."""
    percent: bool

    @property
    def tolerance(self) -> Decimal:
        """Half a unit in the last place written: a figure may be a rounded value."""
        return Decimal(5) / Decimal(10) ** (self.decimals + 1)


@dataclass(frozen=True)
class FigureCheck:
    figures: int
    """How many figures the answer states."""
    unmatched: tuple[str, ...]
    """Figures that match no Financial Fact of a cited Filing and appear in no cited
    passage."""

    @property
    def passed(self) -> bool:
        return not self.unmatched


def figures(text: str) -> list[Figure]:
    """The figures stated in the text, in order.

    Not figures: years (a bare whole number from 1900 to 2100), dates, single-digit
    whole numbers ("3 segments"), and numbers that are part of a label: fiscal periods
    (FY2025, Q3), form types (10-K), Items and Notes (Item 1A), Source tags and Filing
    IDs.
    """
    found: list[Figure] = []
    for m in _FIGURE.finditer(text):
        if _NOT_A_FIGURE_BEFORE.search(text[: m.start()]):
            continue
        whole, fraction = m["whole"].replace(",", ""), m["fraction"] or ""
        scale_word = (m["word"] or m["short"] or "").lower()
        bare = not (m["currency"] or fraction or m["percent"] or scale_word)
        if bare and "," not in m["whole"] and (len(whole) == 1 or 1900 <= int(whole) <= 2100):
            continue
        found.append(
            Figure(
                text=m.group().strip(),
                mantissa=Decimal(whole + fraction),
                decimals=max(len(fraction) - 1, 0),
                scale=_SCALES[scale_word] if scale_word else None,
                percent=bool(m["percent"]),
            )
        )
    return found


def check_figures(
    answer: str, passages: Mapping[int, str], fact_values: Mapping[int, Iterable[int]]
) -> FigureCheck:
    """Every figure in the answer matches a Financial Fact of a Filing the answer cites,
    or appears in a passage the answer cites.

    `passages` maps each of this turn's Source numbers to its text, and `fact_values`
    maps each to the values, in whole US dollars, of the Financial Facts its Filing
    reports. Only the Sources the answer cites count, so a figure for another Report
    Period, or from a Filing the answer never cites, does not pass.

    A figure may be rounded and rescaled: "$416.2 billion" appears in a passage that
    reads "416,161" in a table in millions, and matches a revenue fact of
    416,161,000,000. A percentage must appear in a passage as written.
    """
    cited = source_numbers_cited(answer)
    numbers = {
        abs(Decimal(n.replace(",", "")))
        for number, text in passages.items()
        if number in cited
        for n in _PASSAGE_NUMBER.findall(text)
    }
    facts = [
        abs(Decimal(v)) for number, values in fact_values.items() if number in cited for v in values
    ]
    stated = [f for unit in units(answer) for f in figures(strip_tags(unit.text))]
    unmatched = tuple(
        f.text for f in stated if not (_in_passages(f, numbers) or _is_fact(f, facts))
    )
    return FigureCheck(figures=len(stated), unmatched=unmatched)


def _in_passages(figure: Figure, numbers: set[Decimal]) -> bool:
    rescale = (Decimal(1),) if figure.percent else _RESCALE
    return any(
        abs(n * factor - figure.mantissa) <= figure.tolerance for n in numbers for factor in rescale
    )


def _is_fact(figure: Figure, facts: list[Decimal]) -> bool:
    if figure.percent:
        return False
    scales = (figure.scale,) if figure.scale else _FACT_SCALES
    return any(
        abs(value / scale - figure.mantissa) <= figure.tolerance
        for value in facts
        for scale in scales
    )


# --- Coverage Gaps ----------------------------------------------------------------------

_NOT = r"(?:\bno\b|\bnot\b|n't\b|\bwithout\b|\bnor\b|\bneither\b)"
_GAP_MARKERS: dict[str, re.Pattern[str]] = {
    # A trend asked of a Snapshot Company.
    "snapshot_trend": re.compile(
        r"snapshot|\btrend\b[^.;]{0,20}\b(?:not available|unavailable)"
        r"|\bonly\b[^.;]{0,60}\b(?:19|20)\d\d\b|\b(?:19|20)\d\d\b[^.;]{0,30}\bonly\b"
        r"|\bno (?:earlier|prior|multi-?year|longer)\b"
        rf"|(?:{_NOT}|\bcannot\b|\bunable\b)[^.;]{{0,40}}\b(?:trend|change|compare)",
        re.I,
    ),
    # A named Company is not in the Corpus.
    "missing_company": re.compile(
        r"\bnot\b[^.;]{0,30}\b(?:in|included|part of|covered|among|available|present|found)"
        r"\b[^.;]{0,20}\b(?:corpus|filings|sources|data|documents|dataset)"
        r"|\bno (?:filings?|sources?|data|documents?|10-[KQ]s?)\b"
        r"[^.;]{0,20}\b(?:for|from|on|by|of)\b"
        r"|\b(?:corpus|filings|sources|data|dataset|excerpts)\b[^.;]{0,30}"
        r"(?:do(?:es)? not|don't|doesn't)\s+(?:include|contain|cover|provide|describe|have)"
        r"|\b(?:contains?|includes?|provides?|has|have)\s+no\b[^.;]{0,30}\b(?:filings?|10-[KQ]s?|data|disclosures?)"
        r"|(?:\bdo(?:es)? not|n['’]t)\s+(?:include|contain|cover|provide|describe|have)\b"
        r"|\bno\b[^.;]{0,60}\b(?:included|provided|supplied|available)\b"
        r"|\bno\b(?:\s+[\w’'-]+){0,4}\s+(?:filings?|10-[KQ]s?)\b"
        r"|\bmissing from\b|\bnot (?:in|part of) the corpus",
        re.I,
    ),
    # The answer would rest on GE Capital's FY2014 Filing.
    "stale_filing": re.compile(
        r"\bstale\b|\boutdated\b|\bout of date\b|\bdecade\b|\b(?:ten|10|eleven|11|12) years\b"
        r"|(?:does not|doesn't|do not|cannot|can't|not)\s+(?:describe|reflect|represent|speak)"
        r"|\bnot\b[^.;]{0,30}\b(?:current|today|recent)\b|\bdifferent (?:legal )?entity\b"
        r"|\bonly\b[^.;]{0,40}\b(?:filing|10-K)\b|\b(?:post|after|since)[- ](?:19|20)\d\d\b",
        re.I,
    ),
    # An outlook question whose guidance is not in the Filings.
    "no_guidance": re.compile(
        rf"{_NOT}[^.;]{{0,80}}\b(?:guidance|forecasts?|projections?)\b"
        r"|\b(?:guidance|forecasts?|projections?)\b[^.;]{0,80}"
        r"(?:\bnot\b|n't\b|\babsent\b|\bunavailable\b|\bmissing\b)",
        re.I,
    ),
    # The compared Companies' latest Filings cover different periods.
    "periods_differ": re.compile(
        r"\b(?:periods?|fiscal (?:years?|periods?|quarters?)|year[- ]ends?|reporting dates?)\b"
        r"[^.;]{0,60}\b(?:differ\w*|not (?:the same|aligned|identical|directly comparable)"
        r"|vary|varies|mismatch\w*)"
        r"|\b(?:differ\w*|mismatch\w*|not the same|not aligned|do not align|don't align)\b"
        r"[^.;]{0,40}\b(?:periods?|fiscal|year[- ]ends?|reporting dates?)",
        re.I,
    ),
}
"""What a sentence stating each kind of Coverage Gap says, in any reasonable wording:
the fixed wordings of EDA notebook section 8.6 and the plain variants a model writes."""

_COMPANY_FREE_GAPS = {"periods_differ"}
"""Gaps about the comparison as a whole: stated once, not once per Company."""

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\[(*\"“A-Z])")

_ABBREVIATION_END = re.compile(
    r"(?:(?<![\w.])(?:[A-Z]\.){2,}"  # initialisms: "U.S.", "U.K.", "J.P."
    r"|\b(?:Inc|Corp|Co|Ltd|Mr|Mrs|Ms|Dr|Jr|Sr|St|No|vs|e\.g|i\.e)\.)$"
)
"""The end of a part of a sentence that stops at an abbreviation, not at a full stop:
"... depend on U.S." before "Government ..."."""


@dataclass(frozen=True)
class CoverageGapCheck:
    stated: tuple[str, ...]
    """The kinds of the expected Coverage Gaps the answer states."""
    missing: tuple[str, ...]
    """The kinds of the expected Coverage Gaps it does not state."""

    @property
    def passed(self) -> bool:
        return not self.missing


def check_coverage_gaps(
    answer: str,
    expected: Sequence[CoverageGapLabel],
    names: Mapping[str, Sequence[str]],
) -> CoverageGapCheck:
    """Every expected Coverage Gap is stated in the answer.

    A gap is stated for a Company when a sentence says what the gap's kind says
    (`_GAP_MARKERS`) and either names the Company, or names no Company and sits in a
    paragraph that does ("Tesla's 10-K ... The Sources give no 2026 forecast."). A
    sentence naming no Company also counts when the gap is about one Company only, as
    a closing Coverage note that does not repeat the name usually is. A gap
    about several Companies must be stated for each, except "periods differ", which is
    about the comparison and is stated once. `names` maps a ticker to the ways an answer
    may name the Company (the ticker itself, the name, aliases). It should cover every
    Company an answer may name, including those missing from the Corpus, so a sentence
    about one Company is never taken for another. A label not in `names` is matched by
    itself.
    """
    marked = [(unit.text, s) for unit in units(answer) for s in _sentences(unit.text)]
    stated: list[str] = []
    missing: list[str] = []
    for label in expected:
        marker = _GAP_MARKERS[label.kind]
        hits = [(unit, s) for unit, s in marked if marker.search(s)]
        if label.kind in _COMPANY_FREE_GAPS:
            ok = bool(hits)
        else:
            every = [*names.values(), *((c,) for c in label.companies)]
            single = len(label.companies) == 1
            ok = all(
                any(
                    _names(s, aliases)
                    or ((single or _names(unit, aliases)) and not any(_names(s, a) for a in every))
                    for unit, s in hits
                )
                for aliases in (names.get(c, (c,)) for c in label.companies)
            )
        (stated if ok else missing).append(label.kind)
    return CoverageGapCheck(stated=tuple(stated), missing=tuple(missing))


def _names(sentence: str, aliases: Sequence[str]) -> bool:
    """Whether the sentence names the Company by any alias. All-capital aliases
    (tickers, "GE") match in capitals only; names match in any case and with hyphens
    for spaces ("Bristol-Myers Squibb")."""
    flat = _flatten(sentence)
    for alias in aliases:
        if alias.isupper():
            if re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", sentence):
                return True
        elif re.search(rf"(?<!\w){re.escape(_flatten(alias))}(?!\w)", flat, re.I):
            return True
    return False


def _flatten(text: str) -> str:
    return re.sub(r"[\s\-‐-―]+", " ", text.replace("’", "'"))


# --- Claims, for the Faithfulness judgment ------------------------------------------------


@dataclass(frozen=True)
class Claim:
    """One sentence of an answer and the Source tags it rests on."""

    text: str
    """The sentence without its tags."""
    tags: tuple[str, ...]
    """Empty for a sentence that cites no Source: it is unsupported, with nothing to
    judge it against."""
    heading: str = ""
    """Context, not part of the claim: the nearest heading or bold label above the
    sentence, so "It" keeps its subject. Empty above the first heading."""
    table_header: str = ""
    """Context, not part of the claim: for a table row, the table's header row, so a
    row of numbers keeps its meaning. Empty outside a table."""


def claims(answer: str) -> list[Claim]:
    """The answer's claims: every sentence of the answer, except its structure and what
    it says the Sources could not answer.

    A sentence carries the tags written in it; one without tags of its own rests on all
    the tags of its unit, since a citation often closes a paragraph of several
    sentences. A sentence that rests on no tag is still a claim, with no tags: the judge
    counts it unsupported.

    Not claims: headings (with table header rows and bold labels, which head what
    follows) and the closing Coverage note; and, among the sentences that rest on no
    tag, lead-ins ending in a colon and sentences with nothing to cite: the fixed
    Coverage Gap wordings; the plain variants `check_coverage_gaps` recognises, but
    only when the sentence speaks of the Sources, Filings or Corpus or names a Company
    missing from the Corpus; and sentences that say what the Sources, Filings or
    Corpus lack, naming them. Any other sentence that says something about a Company
    without citing it is a claim, however much it looks like a gap: "Apple's revenue
    grew only 2% in 2024" and "Tesla has no exposure to China tariffs" are claims. A
    sentence that rests on a tag is judged whatever it says.

    Each claim carries its context for the judge: the nearest heading above it and, for
    a table row, the table's header row (`Claim.heading`, `Claim.table_header`).
    """
    found: list[Claim] = []
    for unit in units(answer):
        if unit.exempt and not unit.lead_in:
            continue
        for sentence in _sentences(unit.text, abbreviations=True):
            if _COVERAGE.match(sentence):
                break  # the Coverage note, which says what the Sources could not answer
            text, tags = strip_tags(sentence), tags_in(sentence) or unit.tags
            if not re.search(r"\w", text):
                continue
            if not tags and (text.endswith(":") or _states_gap(text)):
                continue
            found.append(Claim(text, tags, unit.heading, unit.table_header))
    return found


def _states_gap(sentence: str) -> bool:
    """Whether an uncited sentence states a Coverage Gap or says what the Sources lack,
    and so is not a claim (the claim exemption, described beside `_ABSENCE`)."""
    if _FIXED_WORDING.search(sentence) or _RECORDS_LACK.search(sentence):
        return True
    kinds = [kind for kind, marker in _GAP_MARKERS.items() if marker.search(sentence)]
    if not kinds:
        return False
    if "periods_differ" in kinds and _FILING_PERIODS.search(sentence):
        return True  # "The periods differ": the periods are the Filings' Report Periods
    return bool(_RECORDS.search(sentence)) or any(
        _names(sentence, aliases) for aliases in _missing_company_names()
    )


@cache
def _missing_company_names() -> tuple[tuple[str, ...], ...]:
    """The ways an answer may name each Company of the curated list of notable
    Companies missing from the Corpus (assumption 9): its name and aliases."""
    return tuple((c.name, *c.aliases) for c in load_missing_companies())


# --- Answer structure -------------------------------------------------------------------

MIN_WORDS = 300
MAX_WORDS = 600


@dataclass(frozen=True)
class StructureCheck:
    """Whether the answer has the PE-analyst structure of assumption 8."""

    words: int
    """The answer's length in words, without Source tags or Markdown markup."""
    problems: tuple[str, ...]
    """Each way the answer departs from the structure, in words."""

    @property
    def passed(self) -> bool:
        return not self.problems


def check_structure(answer: str, companies: Mapping[str, Sequence[str]]) -> StructureCheck:
    """The structure of assumption 8: a direct answer of two or three sentences first,
    then the points per Company under a heading each, or a comparison table, then a
    closing Coverage note, in 300 to 600 words. `companies` are the Companies the
    answer's Sources come from, each with the names an answer may call it by. An answer
    with no Sources is its Coverage Gaps alone, so it need only open with its direct
    answer."""
    words = _words(answer)
    found = [_opening_problem(answer)]
    if companies:
        found += [
            _per_company_problem(answer, companies),
            _coverage_note_problem(answer),
            f"{words} words, under {MIN_WORDS}" if words < MIN_WORDS else None,
            f"{words} words, over {MAX_WORDS}" if words > MAX_WORDS else None,
        ]
    return StructureCheck(words=words, problems=tuple(p for p in found if p))


def _opening_problem(answer: str) -> str | None:
    """Why the answer does not open with a direct answer of at most three sentences."""
    paragraph = answer.strip().split("\n\n", 1)[0].strip()
    first = paragraph.splitlines()[0] if paragraph else ""
    if not first or _HEADING.match(first) or first.startswith("|") or _LIST_ITEM.match(first):
        return "does not open with a direct answer in prose"
    sentences = [s for s in _sentences(" ".join(paragraph.split())) if len(s.split()) >= 3]
    if len(sentences) > 3:
        return f"opens with a direct answer of {len(sentences)} sentences, not two or three"
    return None


def _per_company_problem(answer: str, companies: Mapping[str, Sequence[str]]) -> str | None:
    """Why an answer about several Companies has neither a heading per Company nor a
    comparison table."""
    if len(companies) < 2:
        return None
    lines = [line.strip() for line in answer.splitlines()]
    if any(_TABLE_SEPARATOR.match(line) for line in lines if line.startswith("|")):
        return None
    headings = [line for line in lines if _HEADING.match(line) or _BOLD_ONLY.match(line)]
    unheaded = [
        ticker
        for ticker, names in companies.items()
        if not any(_mentions(h, names) for h in headings)
    ]
    if unheaded:
        return f"no points per Company (no heading for {', '.join(unheaded)}) or comparison table"
    return None


def _coverage_note_problem(answer: str) -> str | None:
    """Why the answer does not end with a Coverage note: it has none, or a heading of
    another part follows it."""
    lines = [line.strip() for line in answer.splitlines() if line.strip()]
    starts = [
        n for n, line in enumerate(lines) if _COVERAGE.match(line) or _COVERAGE_IN_LINE.search(line)
    ]
    if not starts:
        return "no closing Coverage note"
    if any(_HEADING.match(line) for line in lines[starts[-1] + 1 :]):
        return "the Coverage note is not at the end"
    return None


def _mentions(text: str, names: Sequence[str]) -> bool:
    return any(re.search(rf"\b{re.escape(n)}\b", text, re.I) for n in names)


def _words(answer: str) -> int:
    text = strip_tags(answer)
    return len([w for w in re.split(r"[\s|]+", text) if re.search(r"\w", w)])


def _sentences(text: str, abbreviations: bool = False) -> list[str]:
    """The unit's sentences, a tag written after a full stop kept with the sentence
    before it. A table row is one sentence.

    With `abbreviations` (the claim split), a common abbreviation such as "U.S.",
    "Inc." or "Corp." ends no sentence, even before a capital, unless a tag follows
    it: "Apple relies on the U.S. Government [S1]." is one sentence. The other checks
    split without it, as they always have."""
    if text.startswith("|"):
        return [text]
    parts = _SENTENCE_END.split(text)
    merged: list[str] = []
    for part in parts:
        if abbreviations and merged and _ABBREVIATION_END.search(merged[-1]):
            if not part.startswith("["):
                merged[-1] += " " + part
                continue
        if merged and (run := _TAG_RUN.match(part)):
            merged[-1] += " " + run.group().strip()
            part = part[run.end() :].strip()
            if not part:
                continue
        merged.append(part)
    return merged
