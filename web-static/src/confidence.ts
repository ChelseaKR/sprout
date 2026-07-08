/**
 * Calibrated uncertainty — a mirror of `confidence.py`. Confidence is a transparent
 * function of retrieval evidence, mapped through the same fixed logistic (ADR-0012:
 * midpoint 0.30, steepness 6.0, margin bonus 0.05) as the Python side, so the two
 * implementations must agree bit-for-bit on every rendered confidence.
 */

import type { RetrievedChunk } from "./models.js";
import type { ConfidenceConfig } from "./config.js";

const MIDPOINT = 0.3;
const STEEPNESS = 6.0;
const MARGIN_BONUS = 0.05;

/**
 * Map retrieval evidence to a calibrated confidence in [0, 1] — mirrors
 * `score_confidence`.
 */
export function scoreConfidence(retrieved: readonly RetrievedChunk[], nRendered: number): number {
  if (nRendered === 0 || retrieved.length === 0) {
    return 0.0;
  }
  const scores = retrieved.map((rc) => rc.score).sort((a, b) => b - a);
  const best = scores[0] as number;
  const margin = scores.length > 1 ? best - (scores[1] as number) : best;
  const base = 1.0 / (1.0 + Math.exp(-STEEPNESS * (best - MIDPOINT)));
  const adjusted = base + MARGIN_BONUS * Math.min(margin, 0.3);
  return Math.max(0.0, Math.min(1.0, adjusted));
}

export function shouldAbstain(confidence: number, cfg: ConfidenceConfig): boolean {
  return confidence < cfg.abstain_threshold;
}

export function isLowConfidence(confidence: number, cfg: ConfidenceConfig): boolean {
  return confidence < cfg.low_confidence_threshold;
}
