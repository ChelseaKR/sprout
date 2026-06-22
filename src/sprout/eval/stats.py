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


def is_underpowered(n: int) -> bool:
    """True if the sample is too small to trust the point estimate (< 30)."""
    return n < UNDERPOWERED_N
