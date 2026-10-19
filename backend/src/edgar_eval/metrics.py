"""The harnesses' pure parts: ranking metrics, McNemar's exact test, the sign test, the
bootstrap interval and the case-cluster bootstrap test, and the judge study's agreement
statistics (Cohen's kappa, the Wilson score interval and Fisher's exact test).

A ranking is the list of (Filing ID, Section) pairs an Arm returns, best first, one per
Source. `k=None` means the whole ranking: every Source that reaches the Answer Call.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from math import comb, sqrt
from random import Random
from statistics import NormalDist, fmean
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


@dataclass(frozen=True)
class ClusterBootstrapTest:
    """A one-sided test of a total over cases by the case-cluster bootstrap."""

    total: int
    """The statistic: the per-case differences summed, challenger minus shipped."""
    p_ahead: float
    """One-sided p-value that the challenger is ahead: the share of resampled totals,
    centred under the null, at least `total`."""
    p_behind: float
    """One-sided p-value that the challenger is behind: the share at most `total`."""
    resamples: int
    seed: int


def cluster_bootstrap_test(
    differences: Sequence[int],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> ClusterBootstrapTest:
    """The case-cluster bootstrap test of a total of per-case differences, such as the
    must-state Required Facts a challenger states minus those the shipped choice states
    in each case (ADR 0015).

    Whole cases are resampled with replacement `resamples` times, from a generator
    seeded with `seed`, so facts of one answer move together and the same differences
    give the same p-values. The resampled differences are centred under the null (each
    less the mean difference), and a p-value is the share of resampled totals at least
    as extreme as the observed one, counting the observed one: (1 + hits) / (1 +
    resamples). A centred resampled total is the resampled sum less the observed total,
    so it reaches the observed total `t` when the resampled sum reaches `2t`, a
    comparison of integers. With no case, both p-values are 1."""
    total, n = sum(differences), len(differences)
    if not n:
        return ClusterBootstrapTest(total, 1.0, 1.0, resamples, seed)
    rng = Random(seed)
    sums = [sum(rng.choices(differences, k=n)) for _ in range(resamples)]
    ahead = sum(1 for s in sums if s >= 2 * total)
    behind = sum(1 for s in sums if s <= 2 * total)
    return ClusterBootstrapTest(
        total=total,
        p_ahead=(1 + ahead) / (1 + resamples),
        p_behind=(1 + behind) / (1 + resamples),
        resamples=resamples,
        seed=seed,
    )


def cohen_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    """Cohen's kappa of (label, verdict) pairs: their agreement beyond what chance gives
    with each side's own shares of the categories. None with no pair, or when chance
    alone gives full agreement (both sides use one category), where it is undefined."""
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    categories = {c for pair in pairs for c in pair}
    chance = sum(
        sum(a == c for a, _ in pairs) / n * sum(b == c for _, b in pairs) / n for c in categories
    )
    return None if chance == 1 else (observed - chance) / (1 - chance)


def wilson_interval(count: int, of: int, *, confidence: float = 0.95) -> tuple[float, float] | None:
    """The Wilson score interval of the share `count / of`, or None when `of` is 0."""
    if of == 0:
        return None
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    p, z2 = count / of, z * z
    denominator = 1 + z2 / of
    centre = (p + z2 / (2 * of)) / denominator
    half = z * sqrt(p * (1 - p) / of + z2 / (4 * of * of)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Fisher's exact test, two-sided, of the 2x2 table [[a, b], [c, d]]: the probability,
    with the margins fixed, of a table no more likely than this one."""
    row, column, n = a + b, a + c, a + b + c + d

    def weight(x: int) -> int:
        return comb(column, x) * comb(n - column, row - x)

    observed = weight(a)
    tables = range(max(0, row + column - n), min(row, column) + 1)
    # Integer weights, so ties with the observed table are exact.
    return sum(w for w in map(weight, tables) if w <= observed) / comb(n, row)
