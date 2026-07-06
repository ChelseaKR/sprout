"""Calibrated uncertainty: a [0,1] confidence, abstention, and reliability metrics.

Confidence is a transparent function of *retrieval evidence* — how strongly the best
passage matched and how cleanly it separated from the runner-up — mapped through a fixed
logistic. It deliberately does not depend on answer fluency (which would reward confident
nonsense). Two thresholds turn the score into behaviour: below ``abstain_threshold`` the
assistant refuses rather than guesses; below ``low_confidence_threshold`` it answers but
flags the answer for human review. The reliability diagram and Expected Calibration Error
let the eval harness check that these stated confidences actually track correctness.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from .config import ConfidenceConfig
from .models import RetrievedChunk

# Logistic shape, calibrated against the eval set so stated confidence tracks empirical
# accuracy (mean confidence ~ observed correctness, ECE well under the 0.15 gate) rather
# than saturating near 1.0. Re-fit if the corpus or retrieval changes materially.
# Values per ADR-0012 (supersedes ADR-0005, which documented untested midpoint 0.22 /
# steepness 12.0; an audit on 2026-07-05 found these shipped values -- 0.30/6.0 -- had
# diverged from the ADR since the initial commit, and running the calibration suite
# against both showed the ADR's numbers fail the ECE gate (0.184 > 0.15) while these
# pass it (0.108) -- see ADR-0012 for the full evidence).
_MIDPOINT = 0.30
_STEEPNESS = 6.0
_MARGIN_BONUS = 0.05


def score_confidence(retrieved: Sequence[RetrievedChunk], n_rendered: int) -> float:
    """Map retrieval evidence to a calibrated confidence in [0, 1].

    Returns 0.0 when nothing was rendered (a refusal is maximally uncertain about the
    answer it declined to give). Otherwise a logistic of the best cosine score, nudged
    up by the margin over the second-best passage.
    """
    if n_rendered == 0 or not retrieved:
        return 0.0
    scores = sorted((rc.score for rc in retrieved), reverse=True)
    best = scores[0]
    margin = best - scores[1] if len(scores) > 1 else best
    base = 1.0 / (1.0 + math.exp(-_STEEPNESS * (best - _MIDPOINT)))
    adjusted = base + _MARGIN_BONUS * min(margin, 0.3)
    return max(0.0, min(1.0, adjusted))


def should_abstain(confidence: float, cfg: ConfidenceConfig) -> bool:
    return confidence < cfg.abstain_threshold


def is_low_confidence(confidence: float, cfg: ConfidenceConfig) -> bool:
    return confidence < cfg.low_confidence_threshold


class ReliabilityBin(BaseModel):
    """One bin of a reliability diagram."""

    model_config = ConfigDict(frozen=True)

    lo: float
    hi: float
    count: int
    mean_confidence: float
    accuracy: float


def reliability_diagram(
    pairs: Sequence[tuple[float, bool]], n_bins: int = 10
) -> list[ReliabilityBin]:
    """Bin (confidence, correct) pairs into equal-width bins over [0, 1]."""
    bins: list[ReliabilityBin] = []
    width = 1.0 / n_bins
    for b in range(n_bins):
        lo = b * width
        hi = (b + 1) * width if b < n_bins - 1 else 1.0 + 1e-9
        members = [(c, ok) for c, ok in pairs if lo <= c < hi]
        count = len(members)
        mean_conf = sum(c for c, _ in members) / count if count else 0.0
        acc = sum(1 for _, ok in members if ok) / count if count else 0.0
        bins.append(
            ReliabilityBin(
                lo=round(lo, 4),
                hi=round(min(hi, 1.0), 4),
                count=count,
                mean_confidence=round(mean_conf, 4),
                accuracy=round(acc, 4),
            )
        )
    return bins


def expected_calibration_error(pairs: Sequence[tuple[float, bool]], n_bins: int = 10) -> float:
    """ECE: total-count-weighted average gap between confidence and accuracy."""
    total = len(pairs)
    if total == 0:
        return 0.0
    ece = 0.0
    for b in reliability_diagram(pairs, n_bins):
        if b.count:
            ece += (b.count / total) * abs(b.mean_confidence - b.accuracy)
    return ece
