"""The harnesses' pure parts: ranking metrics, McNemar's exact test, the sign test and
the bootstrap interval.

A ranking is the list of (Filing ID, Section) pairs an Arm returns, best first, one per
Source. `k=None` means the whole ranking: every Source that reaches the Answer Call.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from math import comb
from random import Random
from statistics import fmean
from typing import Literal

Pair = tuple[str, str]
"""A (Filing ID, Section) pair."""

Verdict = Literal["ahead", "behind", "indistinguishable"]

ALPHA = 0.05
"""The two-sided significance level below which the retrieval harness calls a challenger
ahead or behind."""

BOOTSTRAP_SEED = 20261017
"""The fixed seed of every bootstrap interval, so a report's interval is reproducible."""
BOOTSTRAP_RESAMPLES = 10_000


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
    """Cases the challenger got right and the Shipped Arm got wrong (in the sign test,
    cases the challenger scored higher)."""
    shipped_only: int
    """Cases the Shipped Arm got right and the challenger got wrong (in the sign test,
    cases the Shipped Arm scored higher)."""
    p_value: float
    """Two-sided exact p-value: a binomial test of the discordant cases at p = 1/2."""
    verdict: Verdict
    """Two-sided, at ALPHA: the retrieval harness's verdict. The selection rules decide
    on the one-sided p-values instead (`edgar_eval.selection`)."""
    p_ahead: float = 1.0
    """One-sided exact p-value that the challenger is ahead: the chance of at least
    `challenger_only` wins among the discordant cases if both sides were equally good."""
    p_behind: float = 1.0
    """One-sided exact p-value that the challenger is behind: the chance of at most
    `challenger_only` wins among the discordant cases if both sides were equally good."""


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
    return _exact(b, c)


def sign_test(
    challenger: Sequence[float | bool | None], shipped: Sequence[float | bool | None]
) -> McNemarResult:
    """The exact sign test on paired per-case scores: McNemar's test generalised to
    scores that are not pass/fail, such as a case's Fact Recall.

    A case counts for the challenger when it scored higher, for the shipped choice when
    that scored higher, and not at all when they tie or either could not be scored
    (None).
    """
    if len(challenger) != len(shipped):
        raise ValueError("the sign test needs both sides' scores on the same cases")
    pairs = [(c, s) for c, s in zip(challenger, shipped, strict=True) if None not in (c, s)]
    return _exact(sum(1 for c, s in pairs if c > s), sum(1 for c, s in pairs if s > c))


def _exact(b: int, c: int) -> McNemarResult:
    """Binomial tests at p = 1/2 of `b` wins against `c` losses: two-sided, and one-sided
    in each direction."""
    n = b + c
    p = min(1.0, 2 * _tail(n, min(b, c))) if n else 1.0
    verdict: Verdict = "indistinguishable"
    if p < ALPHA:
        verdict = "ahead" if b > c else "behind"
    return McNemarResult(
        challenger_only=b,
        shipped_only=c,
        p_value=p,
        verdict=verdict,
        p_ahead=_tail(n, c),  # at least b wins is at most c losses
        p_behind=_tail(n, b),
    )


def _tail(n: int, k: int) -> float:
    """P(X <= k) for X ~ Binomial(n, 1/2)."""
    return sum(comb(n, i) for i in range(k + 1)) / 2**n


@dataclass(frozen=True)
class Interval:
    """The mean of paired differences with a percentile bootstrap interval around it."""

    mean: float
    low: float
    high: float
    confidence: float
    resamples: int
    seed: int


def bootstrap_interval(
    differences: Sequence[float],
    *,
    confidence: float = 0.95,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> Interval | None:
    """The mean paired difference (challenger minus shipped, per case) and its percentile
    bootstrap interval: the cases resampled with replacement `resamples` times, from a
    generator seeded with `seed`. None with no pair. Shown beside a verdict, never decided
    on (ADR 0011)."""
    if not differences:
        return None
    rng, n = Random(seed), len(differences)
    means = sorted(fmean(rng.choices(differences, k=n)) for _ in range(resamples))
    cut = int((1 - confidence) / 2 * resamples)  # resampled means outside, on each side
    return Interval(
        mean=fmean(differences),
        low=means[cut],
        high=means[resamples - 1 - cut],
        confidence=confidence,
        resamples=resamples,
        seed=seed,
    )
