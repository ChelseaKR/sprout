"""Statistics for honest scoreboards — Wilson confidence intervals, no scipy.

A pass rate over a handful of cases can clear a threshold on luck. Every suite reports a
Wilson 95% confidence interval on its gated rate and flags itself under-powered below 30
items, and the optional statistical gate requires the *lower bound* of that interval to
clear the threshold — so a small, high-variance sample cannot pass quietly.
"""

from __future__ import annotations

# z for a two-sided 95% interval.
Z_95 = 1.959963984540054
UNDERPOWERED_N = 30


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. Returns (low, high) in [0, 1]."""
    if n == 0:
        return (0.0, 0.0)
    phat = successes / n
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * ((phat * (1 - phat) / n + z * z / (4 * n * n)) ** 0.5)
    low = (centre - margin) / denom
    high = (centre + margin) / denom
    return (max(0.0, low), min(1.0, high))


def wilson_difference_interval(
    successes_a: int, n_a: int, successes_b: int, n_b: int, z: float = Z_95
) -> tuple[float, float]:
    """Newcombe's hybrid-score interval for the difference of two independent proportions.

    Returns (low, high) for ``p_a - p_b``. Each proportion gets its own Wilson interval and
    the two are squares-and-added, so the difference inherits Wilson's small-sample
    behaviour instead of a normal approximation that misbehaves as either rate approaches
    0 or 1 — which is exactly the regime a pass-rate slice lives in.

    An empty slice returns the vacuous [-1, 1]: a difference between something and nothing
    is not a measurement, and reporting it as 0.0 would render absence as a value.
    """
    if n_a == 0 or n_b == 0:
        return (-1.0, 1.0)
    p_a, p_b = successes_a / n_a, successes_b / n_b
    low_a, high_a = wilson_interval(successes_a, n_a, z)
    low_b, high_b = wilson_interval(successes_b, n_b, z)
    delta = p_a - p_b
    low = delta - ((p_a - low_a) ** 2 + (high_b - p_b) ** 2) ** 0.5
    high = delta + ((high_a - p_a) ** 2 + (p_b - low_b) ** 2) ** 0.5
    return (max(-1.0, low), min(1.0, high))


def is_underpowered(n: int) -> bool:
    """True if the sample is too small to trust the point estimate (< 30)."""
    return n < UNDERPOWERED_N
