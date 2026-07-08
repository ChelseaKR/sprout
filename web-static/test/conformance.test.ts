/**
 * Cross-language conformance test (EXP-08's "deliverable's spine").
 *
 * `scripts/generate_conformance_fixtures.py` runs the real Python
 * `sprout.answer.Assistant` over every question in `eval/suites/*.yaml` (the same
 * question set the eval harness scores against) and records its answer. This test
 * replays every one of those questions through the TypeScript port loaded from the same
 * exported `index.json`/`config.json` bundle, and asserts the two implementations agree
 * exactly: same rendered text, same citations, same confidence, same refusal reason.
 * Any drift here is a real bug in the port, not a fixture staleness issue, as long as
 * `make web-static-fixtures` was re-run after the last Python pipeline change (CI does
 * this — see `.github/workflows/ci.yml`).
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import assert from "node:assert/strict";
import { test } from "node:test";

import { Assistant } from "../src/answer.js";
import { VectorStore } from "../src/store.js";
import type { WebConfig } from "../src/config.js";
import { answerCitations, answerDisplayText, answerText, type Answer } from "../src/models.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// This file compiles to dist/test/conformance.test.js, so the package root (where
// public/data/*.json and test/fixtures/*.json live, uncompiled) is two levels up.
const ROOT = path.resolve(HERE, "..", "..");

interface FixtureCase {
  id: string;
  suite: string;
  question: string;
  language_requested: string;
  expected: {
    language: string;
    refused: boolean;
    refusal_reason: string | null;
    text: string;
    display_text: string;
    citations: string[];
    confidence: number;
    low_confidence: boolean;
    abstained: boolean;
    is_safety_query: boolean;
    safety_notice: string | null;
    disclosure: string;
    as_of: string | null;
  };
}

interface FixtureFile {
  format_version: number;
  cases: FixtureCase[];
}

function loadJson<T>(relPath: string): T {
  return JSON.parse(readFileSync(path.join(ROOT, relPath), "utf-8")) as T;
}

const config = loadJson<WebConfig>("public/data/config.json");
const indexJson = loadJson<unknown>("public/data/index.json");
const fixtures = loadJson<FixtureFile>("test/fixtures/conformance.json");

const store = VectorStore.fromIndexJson(indexJson);
const assistant = new Assistant(config, store);

assert.equal(fixtures.format_version, 1, "unexpected fixture format version");
assert.ok(fixtures.cases.length > 0, "no conformance fixtures loaded");

for (const fixture of fixtures.cases) {
  test(`conformance: ${fixture.suite}/${fixture.id}`, () => {
    const answer: Answer = assistant.answer(fixture.question, fixture.language_requested);
    const expected = fixture.expected;

    assert.equal(answer.language, expected.language, "language");
    assert.equal(answer.refused, expected.refused, "refused");
    assert.equal(answer.refusal_reason, expected.refusal_reason, "refusal_reason");
    assert.equal(answerText(answer), expected.text, "text");
    assert.equal(answerDisplayText(answer), expected.display_text, "display_text");
    assert.deepEqual(
      answerCitations(answer).map((c) => c.chunk_id),
      expected.citations,
      "citations",
    );
    assert.equal(answer.confidence, expected.confidence, "confidence");
    assert.equal(answer.low_confidence, expected.low_confidence, "low_confidence");
    assert.equal(answer.abstained, expected.abstained, "abstained");
    assert.equal(answer.is_safety_query, expected.is_safety_query, "is_safety_query");
    assert.equal(answer.safety_notice, expected.safety_notice, "safety_notice");
    assert.equal(answer.disclosure, expected.disclosure, "disclosure");
    assert.equal(answer.as_of, expected.as_of, "as_of");
  });
}
