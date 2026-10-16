"""The Answer Call's prompt template, internal to the retrieval seam.

One fixed template with a version constant. Every change to it bumps `PROMPT_VERSION`
and gets an entry in `docs/prompt-iterations.md`, with what changed, why, and its dev
scores before and after.

v2 renders, in this order: the system rules, the Companies each Sector phrase resolved
to (when the question uses one), the Sources grouped by Company, the earlier
conversation, and the latest question. Coverage Gaps and the Financial Facts table join
it in later versions, between the rules and the Sources.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from edgar_rag._chunks import count_tokens

if TYPE_CHECKING:
    from edgar_rag.retrieval import Message, QueryScope, Source

PROMPT_VERSION = "v2"

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
4. When you use a Company's filings, give the filing's form type and fiscal period, and \
say so when the Companies you compare report for different periods.
5. Quote figures exactly as the Sources give them, with their units and periods.
6. When the question names a group of companies ("the major banks"), it was resolved \
through a curated Sector table to the Companies listed under "Companies in scope". Name \
those Companies near the start of the answer, say they come from the Sector table, and \
cover no other company for that group.

Structure the answer for a PE analyst, in Markdown:
- Open with a direct answer in two or three sentences.
- Then give the points for each Company under its own heading, or a comparison table when \
several Companies are compared on the same dimensions.
- End with a short "Coverage" note saying what the Sources could not answer.
- Aim for 300 to 600 words."""

# A Source tag in an earlier answer. It pointed at that turn's Sources, not this turn's.
_SOURCE_TAG = re.compile(r"\s*\[S\d+\](?:\s*\[S\d+\])*")


def render(
    sources: Sequence[Source], history: Sequence[Message], question: str, scope: QueryScope
) -> list[tuple[str, str]]:
    """The prompt as (role, content) messages: the system rules, then one user message
    holding the Companies each Sector phrase resolved to, the Sources, the earlier
    conversation and the question."""
    parts = []
    if scope.sector_phrases:
        parts += ["# Companies in scope", _render_sector_phrases(scope)]
    parts += ["# Sources", _render_sources(sources)]
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
    in HISTORY_MAX_TOKENS. Earlier answers lose their Source tags."""
    lines = [
        f"{'User' if m.role == 'user' else 'Assistant'}: "
        + (_SOURCE_TAG.sub("", m.content) if m.role == "assistant" else m.content).strip()
        for m in history[-HISTORY_TURNS:]
    ]
    while lines and count_tokens("\n\n".join(lines)) > HISTORY_MAX_TOKENS:
        lines.pop(0)
    return "\n\n".join(lines)
