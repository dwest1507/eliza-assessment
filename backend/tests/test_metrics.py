"""The sign test's one-sided form and the bootstrap interval (ADR 0011)."""

from fractions import Fraction

import pytest

from edgar_eval.metrics import bootstrap_interval, sign_test


@pytest.mark.parametrize(
    ("wins", "losses", "p_ahead", "p_behind"),
    [
        # p_ahead is P(X >= wins) and p_behind P(X <= wins), X ~ Binomial(wins + losses, 1/2).
        (5, 0, Fraction(1, 32), Fraction(32, 32)),
        (5, 1, Fraction(7, 64), Fraction(63, 64)),
        (7, 2, Fraction(46, 512), Fraction(502, 512)),
        (1, 4, Fraction(31, 32), Fraction(6, 32)),
        (2, 5, Fraction(120, 128), Fraction(29, 128)),
        (3, 3, Fraction(42, 64), Fraction(42, 64)),
    ],
)
def test_the_one_sided_sign_test_matches_exact_binomial_tails(wins, losses, p_ahead, p_behind):
    # Ties (0.5 against 0.5) and unscored cases count for neither side.
    challenger = [1.0] * wins + [0.0] * losses + [0.5, None]
    shipped = [0.0] * wins + [1.0] * losses + [0.5, 1.0]

    result = sign_test(challenger, shipped)

    assert (result.challenger_only, result.shipped_only) == (wins, losses)
    assert result.p_ahead == pytest.approx(float(p_ahead))
    assert result.p_behind == pytest.approx(float(p_behind))


def test_with_no_case_differing_neither_side_is_ahead():
    result = sign_test([1.0, 0.0], [1.0, 0.0])

    assert (result.p_ahead, result.p_behind) == (1.0, 1.0)


DIFFERENCES = [1.0, 0.5, 0.0, 0.0, -0.5, 1.0, 0.25, 0.0, 0.0, 0.5]


def test_the_bootstrap_interval_is_the_same_for_the_same_seed():
    first = bootstrap_interval(DIFFERENCES, seed=7)

    assert bootstrap_interval(DIFFERENCES, seed=7) == first
    assert bootstrap_interval(DIFFERENCES, seed=8) != first


def test_the_bootstrap_interval_brackets_the_mean_paired_difference():
    interval = bootstrap_interval(DIFFERENCES)

    assert interval.mean == pytest.approx(0.275)
    assert -0.5 < interval.low < interval.mean < interval.high < 1.0
    assert (interval.resamples, interval.confidence) == (10_000, 0.95)


def test_a_constant_difference_has_no_spread_and_no_pair_has_no_interval():
    interval = bootstrap_interval([0.5] * 6)

    assert (interval.low, interval.mean, interval.high) == (0.5, 0.5, 0.5)
    assert bootstrap_interval([]) is None
