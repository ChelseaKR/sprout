/**
 * Calibrated uncertainty — a mirror of `confidence.py`. Confidence is a transparent
 * function of retrieval evidence, mapped through a logistic whose shape comes from the
 * exported config's `confidence.fit` when one has been committed, and from the ADR-0012
 * defaults (midpoint 0.30, steepness 6.0, margin bonus 0.05) when it has not — the same
 * order of preference as `confidence.py::_constants`, so the two implementations agree
 * bit-for-bit on every rendered confidence.
 *
 * They did not, structurally, until 2026-08-28: these were module constants and
 * `scoreConfidence` never read the config, while `export_web_bundle.py` never wrote the
 * fit. The first use of the documented `sprout fit-confidence` workflow would have made
 * the browser and the CLI disagree about abstention, silently (issue #108).
 */

import type { RetrievedChunk } from "./models.js";
import type { ConfidenceConfig } from "./config.js";

// ADR-0012 defaults, used only when no fit is committed. Mirrors `confidence.py`'s
// `_MIDPOINT` / `_STEEPNESS` / `_MARGIN_BONUS`.
const MIDPOINT = 0.3;
const STEEPNESS = 6.0;
const MARGIN_BONUS = 0.05;

function constants(cfg?: ConfidenceConfig): [number, number, number] {
  const fit = cfg?.fit;
  if (fit != null) {
    return [fit.midpoint, fit.steepness, fit.margin_bonus];
  }
  return [MIDPOINT, STEEPNESS, MARGIN_BONUS];
}

/**
 * Map retrieval evidence to a calibrated confidence in [0, 1] — mirrors
 * `score_confidence`. `cfg` is optional so an absent config falls back to the same
 * defaults Python does, rather than to a different answer.
 */
export function scoreConfidence(
  retrieved: readonly RetrievedChunk[],
  nRendered: number,
  cfg?: ConfidenceConfig,
): number {
  if (nRendered === 0 || retrieved.length === 0) {
    return 0.0;
  }
  const [midpoint, steepness, marginBonus] = constants(cfg);
  const scores = retrieved.map((rc) => rc.score).sort((a, b) => b - a);
  const best = scores[0] as number;
  const margin = scores.length > 1 ? best - (scores[1] as number) : best;
  const base = 1.0 / (1.0 + Math.exp(-steepness * (best - midpoint)));
  const adjusted = base + marginBonus * Math.min(margin, 0.3);
  return Math.max(0.0, Math.min(1.0, adjusted));
}

export function shouldAbstain(confidence: number, cfg: ConfidenceConfig): boolean {
  return confidence < cfg.abstain_threshold;
}

export function isLowConfidence(confidence: number, cfg: ConfidenceConfig): boolean {
  return confidence < cfg.low_confidence_threshold;
}

// --- Verbalized confidence bands (EXP-06) ------------------------------------------
//
// A mirror of `confidence.py`'s `confidence_band`. The band turns the calibrated float
// into calibrated *language*, alongside the number and never instead of it — a raw
// "71% confidence" is announced by a screen reader as an undifferentiated figure with
// no sense of whether that is good.
//
// The port had the float and no band at all: `server.py` sends `confidence_band` and
// `confidence_band_label` on every answer, the static site sent neither, and the
// conformance suite could not see the difference because it compared only the fields
// the port already had. So the browser was the less accessible of the two surfaces
// running "the same pipeline".

/** Band keys. Stable machine identifiers — mirrors `confidence.py`'s `BAND_*`. */
export const BAND_WELL_SUPPORTED = "well_supported";
export const BAND_PARTIALLY_SUPPORTED = "partially_supported";
export const BAND_INSUFFICIENT_EVIDENCE = "insufficient_evidence";

/**
 * Map a confidence score to a verbalized band key — mirrors `confidence_band`.
 *
 * Three bands in ascending confidence order: below `abstain_threshold` the assistant
 * abstained, so there is no rendered claim to qualify; `[abstain_threshold, cutoff)` is
 * partially supported; `[cutoff, 1.0]` is well supported.
 *
 * The cut point comes from `cfg.well_supported_cutoff` — shipped in the bundle, not
 * mirrored here — because `derive_band_cutoff` re-derives it from the reliability
 * diagram whenever the confidence function is re-fit, and a constant copied into this
 * file would keep the browser on the pre-fit cut point silently.
 *
 * Callers must pass the *unrounded* confidence, the same value `answer.py` bands on.
 * Banding the rounded copy would differ at a boundary, which is where the band changes.
 */
export function confidenceBand(confidence: number, cfg: ConfidenceConfig): string {
  if (confidence < cfg.abstain_threshold) {
    return BAND_INSUFFICIENT_EVIDENCE;
  }
  if (confidence >= cfg.well_supported_cutoff) {
    return BAND_WELL_SUPPORTED;
  }
  return BAND_PARTIALLY_SUPPORTED;
}
