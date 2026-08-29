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
