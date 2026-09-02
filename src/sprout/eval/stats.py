"""Statistics for honest scoreboards — Wilson confidence intervals, no scipy.

A pass rate over a handful of cases can clear a threshold on luck. Every suite reports a
Wilson 95% confidence interval on its gated rate and flags itself under-powered below 30
items, and the optional statistical gate requires the *lower bound* of that interval to
clear the threshold — so a small, high-variance sample cannot pass quietly.
"""

from __future__ import annotations

import math

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
    # `math.sqrt`, not `** 0.5`: `pow` is not required to be correctly rounded and
    # `sqrt` is, so the two differ in the last bit on some inputs and on some platforms
    # (99 of the 80600 (successes, n) pairs with n<=400, measured on macOS 2026-09-01).
    # These bounds are printed into `docs/audits/eval-report.*`, which is byte-compared
    # against a fresh regeneration, so a last-bit platform difference here is a red build
    # on a file nobody edited.
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    low = (centre - margin) / denom
    high = (centre + margin) / denom
    return (max(0.0, low), min(1.0, high))


def is_underpowered(n: int) -> bool:
    """True if the sample is too small to trust the point estimate (< 30)."""
    return n < UNDERPOWERED_N
