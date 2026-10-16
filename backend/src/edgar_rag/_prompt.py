"""The Answer Call's prompt template, internal to the retrieval seam.

One fixed template with a version constant. Every change to it bumps `PROMPT_VERSION`
and gets an entry in `docs/prompt-iterations.md`, with what changed, why, and its dev
scores before and after.

v7 renders, in this order: the system rules, the Coverage Gaps the answer must state,
the Companies each Sector phrase resolved to (when the question uses one), each
Company's coverage (its class, Filings, Report Periods and Fiscal Periods), the
Financial Facts table (when the question names a metric), the text Sources grouped by
Company, the earlier conversation (the last 10 turns under a token cap, with each
earlier answer's Source tags rewritten as the Filing IDs they cited), and the latest
question.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from edgar_rag._chunks import count_tokens
from edgar_rag._coverage import COVERAGE_LABELS

if TYPE_CHECKING:
    from edgar_rag._coverage import CompanyCoverage, CoverageGap
    from edgar_rag._facts import FactNote, FactRow
    from edgar_rag._query_scope import ScopeFiling
    from edgar_rag.retrieval import Message, QueryScope, Source

PROMPT_VERSION = "v7"

HISTORY_TURNS = 10
HISTORY_MAX_TOKENS = 6_000

SYSTEM_RULES = """\
You are a research assistant for private equity analysts. You answer business questions \
about public companies using only the excerpts from their SEC 10-K and 10-Q filings given \
to you as numbered Sources.

Rules:
1. Use only the Sources. Never use general knowledge, memory or any outside data, even \
for well-known facts. If the Sources do not answer part of the question, say so plainly.
2. Cite every claim with the tag of the Source it comes from, e.g. [S3], placed right \
after the claim. Use several tags when a claim rests on several Sources. Cite only tags \
listed in this turn's Sources.
3. The earlier conversation is there to help you understand the question. It is not \
evidence: never repeat a claim from an earlier answer unless a Source in this turn \
supports it, and then cite that Source.
4. When you use a Company's filings, give the filing's form type, fiscal period and \
report period, as listed under "Coverage", and say so when the Companies you compare \
report for different periods.
5. Take revenue, net income and segment revenue from the Financial Facts table when it \
has them, cite the row's Source tags, and quote figures exactly with their units and \
periods. Label a derived figure as derived: a fourth quarter computed from a 10-K less \
three 10-Qs, a growth rate, or any figure you compute yourself, citing the rows it comes \
from. When a figure is not in the table and you read it from a Source's text instead, say \
it was read from the Filing text. When a Source's text states a change itself ("Revenue \
increased $36.6 billion or 15%") or what drove it, give that too, in its words and with its \
tag, rather than computing the change yourself.
6. When the question names a group of companies ("the major banks"), it was resolved \
through a curated Sector table to the Companies listed under "Companies in scope". Name \
those Companies near the start of the answer, say they come from the Sector table, and \
cover no other company for that group.
7. "Coverage Gaps" lists what the filings cannot answer: a trend asked of a company \
with only a snapshot of filings, a company not in the filings, a stale filing, guidance \
the filings do not contain, or periods that differ. State every gap listed there, in \
the words given, near the start of the answer. Never fill a gap from general \
knowledge: say nothing about a company the filings do not include, never use a filing \
listed as left out, and never present MD&A commentary as the company's guidance.
8. Be specific. For each point, give the particulars the Sources state: the laws and \
programs, products, people, places, dates, amounts and percentages they name, in their \
words. Never reduce them to broad categories ("regulatory risk", "pricing pressure") \
that would fit any company.

Structure the answer for a PE analyst, in Markdown:
- Open with the direct answer: two or three sentences of prose, citing their Sources like \
any other claim. Put nothing before it: no heading, list or table.
- Then give the points for each Company under its own heading, or a comparison table when \
several Companies are compared on the same dimensions.
- Always end with a short "Coverage" note, even when there is no Coverage Gap: repeat the \
Coverage Gaps (or say there are none) and say what else the Sources could not answer.
- Write 300 to 600 words. When the question is narrow, reach 300 words with the specifics \
of rule 8 that bear on it (what drove a figure, the segments, periods or plans behind it, \
the risks the Sources attach to it), never with repetition or general knowledge. When the \
Sources hold more than 600 words can carry, keep the most material points. Only an answer \
whose question the Sources cannot answer at all may be shorter."""

# A run of Source tags in an earlier answer ("[S1]", "[S1][S2]", "[S3, S1]"). They
# pointed at that turn's Sources, not this turn's.
_SOURCE_TAGS = re.compile(r"(\s*)((?:\[S\d+(?:\s*[,;]\s*S\d+)*\]\s*)*\[S\d+(?:\s*[,;]\s*S\d+)*\])")
_TAG = re.compile(r"S\d+")


def render(
    sources: Sequence[Source],
    history: Sequence[Message],
    question: str,
    scope: QueryScope,
    coverage: Sequence[CompanyCoverage] = (),
    gaps: Sequence[CoverageGap] = (),
    facts: Sequence[FactRow] = (),
    notes: Sequence[FactNote] = (),
) -> list[tuple[str, str]]:
    """The prompt as (role, content) messages: the system rules, then one user message
    holding the Coverage Gaps, the Companies each Sector phrase resolved to, each
    Company's coverage, the Financial Facts, the text Sources, the earlier conversation
    and the question."""
    parts = ["# Coverage Gaps", "\n".join(f"- {gap.text}" for gap in gaps) or "None."]
    if scope.sector_phrases:
        parts += ["# Companies in scope", _render_sector_phrases(scope)]
    if coverage:
        parts += ["# Coverage", _render_coverage(coverage)]
    if scope.metrics:
        parts += ["# Financial Facts", _render_facts(sources, facts, notes)]
    parts += ["# Sources", _render_sources([s for s in sources if s.kind == "text"])]
    if earlier := _render_history(history):
        parts += ["# Earlier conversation (context only, not evidence)", earlier]
    parts += ["# Question", question.strip()]
    return [("system", SYSTEM_RULES), ("user", "\n\n".join(parts))]


def _render_sector_phrases(scope: QueryScope) -> str:
    names = {c.ticker: f"{c.name} ({c.ticker})" for c in scope.companies}
    lines = []
    for phrase in scope.sector_phrases:
        basis = " or ".join(phrase.values)
        covered = ", ".join(names[t] for t in phrase.tickers) or "no Company in the Corpus"
        lines.append(
            f'"{phrase.phrase}" was resolved through the Sector table ({phrase.column}: '
            f"{basis}) to: {covered}."
        )
    return "\n".join(lines)


def _render_coverage(coverage: Sequence[CompanyCoverage]) -> str:
    """One paragraph per Company: its coverage class, the span of its Filings in the
    Corpus, the Filings in the time window with their Report and Fiscal Periods, and any
    stale Filing left out."""
    blocks = []
    for company in coverage:
        kind = COVERAGE_LABELS.get(company.coverage or "", "coverage unknown")
        held = company.filings
        if len(held) > 1:
            span = f"{len(held)} Filings in the Corpus, {_period(held[0])} to {_period(held[-1])}"
        elif held:
            span = f"1 Filing in the Corpus, {_period(held[0])}"
        else:
            span = "no Filings in the Corpus"
        lines = [f"{company.name} ({company.ticker}): {kind}; {span}."]
        if company.in_scope:
            lines.append(
                "In scope: "
                + "; ".join(
                    f"{f.filing_id} ({f.form_type} {_period(f)}, Report Period {f.report_period})"
                    for f in company.in_scope
                )
                + "."
            )
        else:
            lines.append("In scope: none.")
        if company.left_out:
            ids = ", ".join(f.filing_id for f in company.left_out)
            lines.append(f"Stale, left out: {ids}.")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _period(filing: ScopeFiling) -> str:
    return filing.fiscal_period or f"period to {filing.report_period}"


_FACTS_INTRO = (
    "Figures extracted from the Filings' income statements and segment tables. Each tag "
    "below is the Financial Facts of one Filing; cite the tags a row lists. Values are in "
    "US dollars. Rows marked derived are computed from the rows they cite, not reported."
)


def _render_facts(
    sources: Sequence[Source], facts: Sequence[FactRow], notes: Sequence[FactNote]
) -> str:
    from edgar_rag._facts import money, percent

    blocks = []
    if facts:
        blocks.append(_FACTS_INTRO)
        blocks.append("\n".join(f"[{s.tag}] {s.label}" for s in sources if s.kind == "facts"))
        lines = [
            "| Company | Metric | Fiscal Period | Period | Value | Basis | "
            "Change from a year earlier (derived) | Sources |",
            "|---|---|---|---|---|---|---|---|",
        ]
        reported = {
            (s.tag, f.metric, f.segment, f.months): f.value
            for s in sources
            if s.kind == "facts"
            for f in s.facts
        }
        for r in facts:
            basis = f'reported as "{r.label}"'
            if r.derived:
                parts = [
                    f"{money(reported[(tag, r.metric, r.segment, months)])} [{tag}]"
                    for tag, months in zip(r.sources, (12, 3, 3, 3), strict=True)
                ]
                basis = f"derived: {r.derived}, {parts[0]} less {', '.join(parts[1:])}"
            change = (
                f"{percent(r.year_on_year)} " + " ".join(f"[{t}]" for t in r.year_on_year_sources)
                if r.year_on_year is not None
                else ""
            )
            lines.append(
                f"| {r.ticker} | {r.metric_name} | {r.fiscal_period} | "
                f"{r.months} months ended {r.report_period} | {money(r.value)} | {basis} | "
                f"{change} | {' '.join(f'[{t}]' for t in r.sources)} |"
            )
        blocks.append("\n".join(lines))
    else:
        blocks.append("No Financial Facts were found for this question.")
    if notes:
        blocks.append("\n".join(f"- {n.text}" for n in notes))
    return "\n\n".join(blocks)


def _render_sources(sources: Sequence[Source]) -> str:
    if not sources:
        return "No Sources were found for this question."
    blocks: list[str] = []
    company = None
    for source in sources:
        if source.ticker != company:
            company = source.ticker
            blocks.append(f"## {source.company} ({source.ticker})")
        blocks.append(f"[{source.tag}] {source.label}\n{source.text}")
    return "\n\n".join(blocks)


def _render_history(history: Sequence[Message]) -> str:
    """The last HISTORY_TURNS messages, oldest first, dropping the oldest until they fit
    in HISTORY_MAX_TOKENS. An earlier answer's Source tags are rewritten as the Filing IDs
    they cited, or dropped when the message doesn't say which Filings those were."""
    lines = [
        f"{'User' if m.role == 'user' else 'Assistant'}: "
        + (_without_tags(m) if m.role == "assistant" else m.content).strip()
        for m in history[-HISTORY_TURNS:]
    ]
    while lines and count_tokens("\n\n".join(lines)) > HISTORY_MAX_TOKENS:
        lines.pop(0)
    return "\n\n".join(lines)


def _without_tags(message: Message) -> str:
    """An earlier answer with each run of Source tags replaced by the Filing IDs they
    cited, in parentheses: "[S1][S2]" becomes "(AAPL_10-K_2025-09-27; AAPL_10-Q_...)"."""
    cited = getattr(message, "sources", None) or {}

    def rewrite(m: re.Match[str]) -> str:
        ids = dict.fromkeys(cited[t] for t in _TAG.findall(m.group(2)) if t in cited)
        return f"{m.group(1)}({'; '.join(ids)})" if ids else ""

    return _SOURCE_TAGS.sub(rewrite, message.content)
