import assert from "node:assert/strict";
import { test } from "node:test";

import { scoreConfidence } from "../src/confidence.js";
import type { RetrievedChunk } from "../src/models.js";
import type { ConfidenceConfig } from "../src/config.js";

function makeChunk(score: number): RetrievedChunk {
  return {
    chunk: {
      chunk_id: "c1",
      doc_id: "d1",
      title: "Monstera Care",
      source: "corpus",
      topic: "watering",
      language: "en",
      text: "test",
      source_name: "test source",
      url: "http://example.com",
      license: "CC0",
      fetch_date: "2026-01-01",
    },
    score,
  };
}

test("scoreConfidence falls back to defaults when fit is not present", () => {
  const retrieved = [makeChunk(0.5), makeChunk(0.3)];
  const cfgWithoutFit: ConfidenceConfig = {
    abstain_threshold: 0.25,
    low_confidence_threshold: 0.5,
  };
  const conf1 = scoreConfidence(retrieved, 1);
  const conf2 = scoreConfidence(retrieved, 1, cfgWithoutFit);
  assert.equal(conf1, conf2);
});

test("scoreConfidence uses fitted constants when fit is provided", () => {
  const retrieved = [makeChunk(0.5), makeChunk(0.3)];
  const cfgWithFit: ConfidenceConfig = {
    abstain_threshold: 0.25,
    low_confidence_threshold: 0.5,
    fit: {
      midpoint: 0.5,
      steepness: 10.0,
      margin_bonus: 0.1,
    },
  };
  const defaultConf = scoreConfidence(retrieved, 1);
  const fittedConf = scoreConfidence(retrieved, 1, cfgWithFit);
  assert.notEqual(defaultConf, fittedConf);

  // At best = 0.5, with midpoint = 0.5:
  // base = 1 / (1 + exp(-10 * 0)) = 0.5
  // margin = 0.2
  // adjusted = 0.5 + 0.1 * 0.2 = 0.52
  assert.equal(Math.round(fittedConf * 100) / 100, 0.52);
});
