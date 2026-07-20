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

from .config import ConfidenceConfig, RetrievalConfig
from .determinism import sha256_of_obj
from .models import RetrievedChunk

# Fallback logistic shape, used whenever ``config.confidence.fit`` is absent (a fresh
# install, or before ``sprout fit-confidence`` has ever been run). Values per ADR-0012
# (supersedes ADR-0005, which documented untested midpoint 0.22 / steepness 12.0; an
# audit on 2026-07-05 found these shipped values -- 0.30/6.0 -- had diverged from the ADR
# since the initial commit, and running the calibration suite against both showed the
# ADR's numbers fail the ECE gate (0.184 > 0.15) while these pass it (0.108) -- see
# ADR-0012 for the full evidence).
#
# Once a fit exists (ADR-0016, ``sprout fit-confidence``), ``score_confidence`` reads
# ``config.confidence.fit.{midpoint,steepness,margin_bonus}`` instead of these globals --
# they remain only as the documented, evidence-backed default for a fresh install.
_MIDPOINT = 0.30
_STEEPNESS = 6.0
_MARGIN_BONUS = 0.05


def best_and_margin(retrieved: Sequence[RetrievedChunk]) -> tuple[float, float]:
    """The best cosine score and its margin over the runner-up, or ``(0.0, 0.0)`` if
    nothing was retrieved. Shared by ``score_confidence`` and the fit-confidence
    evidence collector so both read the same evidence definition."""
    if not retrieved:
        return 0.0, 0.0
    scores = sorted((rc.score for rc in retrieved), reverse=True)
    best = scores[0]
    margin = best - scores[1] if len(scores) > 1 else best
    return best, margin


def _constants(cfg: ConfidenceConfig | None) -> tuple[float, float, float]:
    """Fitted constants if a fit has been recorded in config, else the ADR-0012 default."""
    if cfg is not None and cfg.fit is not None:
        return cfg.fit.midpoint, cfg.fit.steepness, cfg.fit.margin_bonus
    return _MIDPOINT, _STEEPNESS, _MARGIN_BONUS


def score_confidence(
    retrieved: Sequence[RetrievedChunk],
    n_rendered: int,
    cfg: ConfidenceConfig | None = None,
) -> float:
    """Map retrieval evidence to a calibrated confidence in [0, 1].

    Returns 0.0 when nothing was rendered (a refusal is maximally uncertain about the
    answer it declined to give). Otherwise a logistic of the best cosine score, nudged
    up by the margin over the second-best passage. The logistic's constants come from
    ``cfg.fit`` (a provenance-stamped artifact written by ``sprout fit-confidence``) when
    present, else the ADR-0012 default -- see the module docstring.
    """
    if n_rendered == 0 or not retrieved:
        return 0.0
    best, margin = best_and_margin(retrieved)
    midpoint, steepness, margin_bonus = _constants(cfg)
    base = 1.0 / (1.0 + math.exp(-steepness * (best - midpoint)))
    adjusted = base + margin_bonus * min(margin, 0.3)
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


def retrieval_config_fingerprint(cfg: RetrievalConfig) -> str:
    """Content hash of the retrieval config a fit was measured against.

    A fitted logistic answers "what evidence scale did this midpoint/steepness see?" --
    if retrieval settings change materially (embedding dim, hybrid weighting, dedup
    threshold, ...) the old fit's evidence scale may no longer apply. Stamped into
    ``ConfidenceFit.retrieval_config_hash`` at fit time and re-checked by
    ``fit_drift_warning`` before trusting a stale fit.
    """
    return sha256_of_obj(cfg.model_dump())


def fit_drift_warning(cfg: ConfidenceConfig, retrieval: RetrievalConfig) -> str | None:
    """``None`` if there is no fit, or the fit still matches the live retrieval config;
    otherwise a message explaining that retrieval changed since the fit and it should be
    redone (FIX-08 / ADR-0016's drift check)."""
    if cfg.fit is None:
        return None
    live = retrieval_config_fingerprint(retrieval)
    if live == cfg.fit.retrieval_config_hash:
        return None
    return (
        f"confidence.fit is stale: it was fitted against retrieval config "
        f"{cfg.fit.retrieval_config_hash[:12]} but the live retrieval config is now "
        f"{live[:12]}. Retrieval changed since this fit (FIX-07/EXP-03-style change) -- "
        "re-run `sprout fit-confidence` before trusting these constants."
    )
