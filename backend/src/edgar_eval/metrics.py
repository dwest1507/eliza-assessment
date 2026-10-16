"""The retrieval harness's pure parts: ranking metrics and McNemar's exact test.

A ranking is the list of (Filing ID, Section) pairs an Arm returns, best first, one per
Source. `k=None` means the whole ranking: every Source that reaches the Answer Call.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from math import comb
from typing import Literal

Pair = tuple[str, str]
"""A (Filing ID, Section) pair."""

Verdict = Literal["ahead", "behind", "indistinguishable"]

ALPHA = 0.05
"""The significance level below which a challenger is called ahead or behind."""


def hit_at_k(ranked: Sequence[Pair], expected: Collection[Pair], k: int | None) -> bool:
    """Whether any expected pair is among the first `k` of the ranking."""
    return any(pair in expected for pair in ranked[:k])


def recall_at_k(ranked: Sequence[Pair], expected: Collection[Pair], k: int | None) -> float:
    """The share of the expected pairs found among the first `k` of the ranking."""
    found = set(ranked[:k]) & set(expected)
    return len(found) / len(set(expected))


def reciprocal_rank(ranked: Sequence[Pair], expected: Collection[Pair]) -> float:
    """One over the rank of the first expected pair in the whole ranking, or 0."""
    for rank, pair in enumerate(ranked, start=1):
        if pair in expected:
            return 1 / rank
    return 0.0


@dataclass(frozen=True)
class McNemarResult:
    challenger_only: int
    """Cases the challenger got right and the Shipped Arm got wrong."""
    shipped_only: int
    """Cases the Shipped Arm got right and the challenger got wrong."""
    p_value: float
    """Two-sided exact p-value: a binomial test of the discordant cases at p = 1/2."""
    verdict: Verdict


def mcnemar_exact(challenger: Sequence[bool], shipped: Sequence[bool]) -> McNemarResult:
    """Compare two Arms' per-case outcomes on the same cases, question by question.

    Cases both Arms got right, or both got wrong, say nothing about which is better and
    are ignored. The challenger is `ahead` or `behind` only when the split of the
    remaining cases would be unlikely (p < ALPHA) if the two Arms were equally good.
    """
    if len(challenger) != len(shipped):
        raise ValueError("McNemar's test needs both Arms' outcomes on the same cases")
    b = sum(1 for c, s in zip(challenger, shipped, strict=True) if c and not s)
    c = sum(1 for ch, s in zip(challenger, shipped, strict=True) if s and not ch)
    n = b + c
    p = min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / 2**n) if n else 1.0
    verdict: Verdict = "indistinguishable"
    if p < ALPHA:
        verdict = "ahead" if b > c else "behind"
    return McNemarResult(challenger_only=b, shipped_only=c, p_value=p, verdict=verdict)
