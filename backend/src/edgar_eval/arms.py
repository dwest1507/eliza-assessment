"""The retrieval Arms, all defined here. The FTS5 Arm is the Shipped Arm (ADR 0002).

An Arm turns a conversation into the ranked (Filing ID, Section) pairs of the Sources
it would put in the Answer Call. Challenger Arms (dense embeddings, a hybrid, a
re-ranker) are added to `ARMS` and compared with the Shipped Arm by the harness. Every
Arm runs inside the Query Scope's hard filters.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import zip_longest
from pathlib import Path

from edgar_eval.metrics import Pair
from edgar_eval.retrieval import Arm
from edgar_rag.retrieval import Message, prepare_answer_context


def fts5(messages: Sequence[Message], index: Path) -> list[Pair]:
    """The Sources of the shipped retrieval seam, `bm25()` over FTS5 within each Company.

    Each Company in scope is retrieved separately with its own share of the context
    budget, and its Sources are numbered after the previous Company's. Ranking them by
    number would put the last Company's best Source behind every other Company's worst,
    so the ranking takes each Company's next-best Source in turn instead.

    Facts Sources are left out: they are Financial Facts looked up by rule, not text
    retrieved by an Arm, and the Golden Set labels Sections.
    """
    sources = prepare_answer_context(messages, index).sources
    per_company: dict[str, list[Pair]] = {}
    for source in (s for s in sources if s.kind == "text"):
        per_company.setdefault(source.ticker, []).append((source.filing_id, source.section))
    return [
        pair for turn in zip_longest(*per_company.values()) for pair in turn if pair is not None
    ]


ARMS: tuple[Arm, ...] = (
    Arm(
        name="fts5",
        description="SQLite FTS5 bm25() within each Company's hard filter (ADR 0002)",
        retrieve=fts5,
        shipped=True,
    ),
)
