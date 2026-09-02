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


# --- Verbalized confidence bands (EXP-06) -----------------------------------------
#
# A raw float ("confidence 0.71") is poorly read by lay users and by screen readers,
# which announce it as an undifferentiated number with no sense of "is that good?".
# These bands turn the calibrated number into calibrated *language* -- but the band is
# always rendered ALONGSIDE the float, never instead of it: the number stays the
# ground truth (and what the calibration suite gates on); the band is an accessible
# gloss on it.
#
# Band keys are stable, machine-checkable identifiers (used for aria attributes, CSS
# hooks, and eval assertions); ``Config.prompts`` carries the localized label text
# shown to users, following the same *_by_lang pattern as ``refusal_by_lang`` etc.

BAND_WELL_SUPPORTED = "well_supported"
BAND_PARTIALLY_SUPPORTED = "partially_supported"
BAND_INSUFFICIENT_EVIDENCE = "insufficient_evidence"

# Target n-weighted accuracy the "well-supported" band must clear.
_WELL_SUPPORTED_ACCURACY = 0.75

# The well-supported / partially-supported cut point, DERIVED (not invented) from the
# committed reliability diagram in docs/audits/eval-report.json (calibration suite,
# n=98): scanning populated bins from the top down and accumulating n-weighted
# accuracy --
#   [0.9,1.0) n=7  acc=0.857  -> cum acc=0.857
#   [0.8,0.9) n=28 acc=0.821  -> cum acc=0.829
#   [0.7,0.8) n=23 acc=0.696  -> cum acc=0.776   (still >= target)
#   [0.6,0.7) n=20 acc=0.550  -> cum acc=0.718   (drops below target -- stop)
# -- the lowest bin edge that keeps cumulative accuracy >= _WELL_SUPPORTED_ACCURACY is
# 0.70. Re-derive with `derive_band_cutoff` against a fresh reliability diagram
# whenever the confidence function is re-fit (see the _MIDPOINT/_STEEPNESS note above,
# and ADR-0012) -- a cutoff fit to a stale diagram is exactly the kind of drift the
# calibration suite exists to catch.
_DEFAULT_WELL_SUPPORTED_CUTOFF = 0.70


def derive_band_cutoff(
    bins: Sequence[ReliabilityBin], target_accuracy: float = _WELL_SUPPORTED_ACCURACY
) -> float:
    """Derive the well-supported/partially-supported cut point from a reliability diagram.

    Scans populated bins from highest confidence downward, accumulating an n-weighted
    accuracy. The cutoff is the lower edge of the lowest bin at which that cumulative
    accuracy still clears ``target_accuracy``. Conservative by construction: if even the
    top bin misses the target the cutoff stays at 1.0 (nothing qualifies as
    well-supported) rather than picking an optimistic value from noisy data.
    """
    populated = sorted((b for b in bins if b.count), key=lambda b: b.lo, reverse=True)
    cum_n = 0
    cum_hits = 0.0
    cutoff = 1.0
    for b in populated:
        cum_n += b.count
        cum_hits += b.accuracy * b.count
        if cum_hits / cum_n >= target_accuracy:
            cutoff = b.lo
        else:
            break
    return cutoff


def confidence_band(
    confidence: float,
    cfg: ConfidenceConfig,
    cutoff: float = _DEFAULT_WELL_SUPPORTED_CUTOFF,
) -> str:
    """Map a confidence score to a verbalized band key.

    Three bands, in ascending confidence order:
    - below ``cfg.abstain_threshold``: the assistant abstains, so there is no rendered
      claim to qualify -- the band names the refusal itself, not a stated fact.
    - ``[abstain_threshold, cutoff)``: "partially supported -- verify" (localized).
    - ``[cutoff, 1.0]``: "well-supported" (localized).

    ``cutoff`` defaults to the value derived from the committed reliability diagram
    (see module docstring); pass the output of :func:`derive_band_cutoff` against a
    fresh diagram after a confidence re-fit.
    """
    if confidence < cfg.abstain_threshold:
        return BAND_INSUFFICIENT_EVIDENCE
    if confidence >= cutoff:
        return BAND_WELL_SUPPORTED
    return BAND_PARTIALLY_SUPPORTED


class CoveragePoint(BaseModel):
    """One point on a selective-prediction coverage/risk curve.

    ``coverage`` is the fraction of labeled cases whose stated confidence clears
    ``threshold`` (i.e., the fraction the system would *answer* if that threshold were the
    abstain cutoff); ``risk`` is the error rate — 1 minus accuracy — among exactly those
    covered cases. A well-calibrated system trades coverage for risk monotonically: raising
    the threshold should never increase risk. This is a report-only diagnostic (EXP/E4);
    it does not gate anything the ECE/abstention checks do not already gate.

    ``risk`` is ``None`` — not ``0.0`` — when ``n_covered`` is zero. An error rate over an
    empty set is undefined, and a curve whose top point reports zero risk at zero coverage
    plots as "abstain from everything and be perfectly safe", which is a claim no data
    supports. Callers must decide what to do with the absence rather than read a number
    that was never measured.
    """

    model_config = ConfigDict(frozen=True)

    threshold: float
    coverage: float
    risk: float | None
    n_covered: int


# Standard thresholds the curve is reported at, matching the reliability-diagram bin edges
# so the two diagnostics read side by side. 0.25 is the engine's own abstain_threshold
# (ADR-0012, supersedes ADR-0005).
DEFAULT_COVERAGE_THRESHOLDS: tuple[float, ...] = (
    0.0,
    0.1,
    0.2,
    0.25,
    0.3,
    0.4,
    0.5,
    0.6,
    0.7,
    0.8,
    0.9,
)


def coverage_risk_curve(
    pairs: Sequence[tuple[float, bool]],
    thresholds: Sequence[float] = DEFAULT_COVERAGE_THRESHOLDS,
) -> list[CoveragePoint]:
    """Selective-prediction coverage/risk tradeoff over (confidence, correct) pairs.

    For each threshold, "covered" cases are those with ``confidence >= threshold`` — the
    cases the system would answer if abstention were cut at that threshold. Coverage is
    the covered fraction of ``pairs``; risk is the error rate restricted to the covered
    subset, and ``None`` when nothing is covered, because an error rate over an empty set
    is undefined and reporting it as ``0.0`` would publish "zero risk" where the truth is
    "no observation". Thresholds are de-duplicated and sorted ascending; ``pairs`` may be
    empty, in which case every point has zero coverage and no risk to report.
    """
    total = len(pairs)
    points: list[CoveragePoint] = []
    for t in sorted(set(thresholds)):
        covered = [ok for c, ok in pairs if c >= t]
        n_covered = len(covered)
        coverage = n_covered / total if total else 0.0
        risk = (1.0 - sum(covered) / n_covered) if n_covered else None
        points.append(
            CoveragePoint(
                threshold=round(t, 4),
                coverage=round(coverage, 4),
                risk=None if risk is None else round(risk, 4),
                n_covered=n_covered,
            )
        )
    return points
