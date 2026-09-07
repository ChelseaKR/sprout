/**
 * The confidence band's branches that the corpus cannot reach.
 *
 * `conformance.test.ts` compares the band over 238 real cases and covers all three
 * bands in both languages, which is the check that matters — but three branches are
 * structurally unreachable from a bundle exported from this repository, and an
 * unreachable branch that looks tested is worse than one that is honestly untested:
 *
 * - **The cut points themselves.** Every fixture sits somewhere in a band, not at its
 *   edge; a `>` written where `>=` belongs moves nothing. Only a synthetic config whose
 *   thresholds land exactly on a chosen confidence reaches the comparison operator.
 * - **The label fallbacks.** `confidenceBandLabelFor` falls back language -> English ->
 *   the band key. `config/sprout.yaml` gives every band a label in every supported
 *   language, so neither fallback rung ever executes against a real bundle.
 * - **A bundle with no cut point.** `assertBundleIsCurrent` refuses one, because an
 *   absent cutoff compares as `confidence >= undefined` — false for every score — and
 *   would silently label every answered question "partially supported".
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BAND_INSUFFICIENT_EVIDENCE,
  BAND_PARTIALLY_SUPPORTED,
  BAND_WELL_SUPPORTED,
  confidenceBand,
} from "../src/confidence.js";
import { assertBundleIsCurrent, confidenceBandLabelFor } from "../src/config.js";
import type { ConfidenceConfig, WebConfig } from "../src/config.js";

const CFG: ConfidenceConfig = {
  abstain_threshold: 0.25,
  low_confidence_threshold: 0.5,
  well_supported_cutoff: 0.7,
};

test("band cut points are closed above and open below, exactly as confidence_band is", () => {
  // `confidence_band` in Python: `< abstain_threshold` is insufficient, `>= cutoff` is
  // well-supported, everything between is partially supported. Both boundaries are
  // asserted from both sides, because a `<=`/`<` slip is invisible anywhere else.
  assert.equal(confidenceBand(0.2499, CFG), BAND_INSUFFICIENT_EVIDENCE);
  assert.equal(confidenceBand(0.25, CFG), BAND_PARTIALLY_SUPPORTED);
  assert.equal(confidenceBand(0.6999, CFG), BAND_PARTIALLY_SUPPORTED);
  assert.equal(confidenceBand(0.7, CFG), BAND_WELL_SUPPORTED);
  assert.equal(confidenceBand(1.0, CFG), BAND_WELL_SUPPORTED);
  assert.equal(confidenceBand(0.0, CFG), BAND_INSUFFICIENT_EVIDENCE);
});

test("the cut point is read from the bundle, not from a constant in this file", () => {
  // The whole reason `well_supported_cutoff` is exported rather than mirrored: after a
  // `sprout fit-confidence` re-derives it, a hand-copied twin would keep the browser on
  // the old cut point and nothing would fail. Moving it here must move the band.
  const shifted: ConfidenceConfig = { ...CFG, well_supported_cutoff: 0.9 };
  assert.equal(confidenceBand(0.8, CFG), BAND_WELL_SUPPORTED);
  assert.equal(confidenceBand(0.8, shifted), BAND_PARTIALLY_SUPPORTED);
});

function configWithLabels(labels: Record<string, Record<string, string>>): WebConfig {
  return { prompts: { confidence_band_labels: labels } } as unknown as WebConfig;
}

test("band labels fall back language -> English -> the band key", () => {
  const cfg = configWithLabels({
    well_supported: { en: "well-supported", es: "bien respaldada" },
    partially_supported: { en: "partially supported — verify" },
  });
  assert.equal(confidenceBandLabelFor(cfg, "well_supported", "es"), "bien respaldada");
  // No Spanish label for this band: English, not silence.
  assert.equal(
    confidenceBandLabelFor(cfg, "partially_supported", "es"),
    "partially supported — verify",
  );
  // No entry for this band at all: the key itself, which reads as a missing
  // translation. The empty string would read as "this answer has no band", which is a
  // different and untrue claim.
  assert.equal(
    confidenceBandLabelFor(cfg, "insufficient_evidence", "en"),
    BAND_INSUFFICIENT_EVIDENCE,
  );
});

test("a bundle with no cut point is refused rather than defaulted", () => {
  const provenance = { corpus_fingerprint: "sha256:abc" };
  const withCutoff = {
    format_version: 3,
    provenance,
    confidence: { well_supported_cutoff: 0.7 },
  } as unknown as WebConfig;
  assert.doesNotThrow(() => {
    assertBundleIsCurrent(withCutoff);
  });

  for (const missing of [undefined, null, "0.7", Number.NaN]) {
    const bundle = {
      format_version: 3,
      provenance,
      confidence: { well_supported_cutoff: missing },
    } as unknown as WebConfig;
    assert.throws(
      () => {
        assertBundleIsCurrent(bundle);
      },
      /well_supported_cutoff/,
      `a cutoff of ${String(missing)} must be refused: banding against it would put ` +
        "every answered question in the same band and read as a calibration result",
    );
  }
});
