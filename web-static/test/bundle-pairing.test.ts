/**
 * The bundle's provenance block, held to the index the page actually answers from.
 *
 * `config.json` records `index_chunks` and `index_chunk_ids_sha256` for one reason: so
 * a config can be shown to describe the `index.json` beside it. `sprout bundle-check`
 * makes that comparison at build time and its own failure message says what a mismatch
 * means — *"config.json and the index beside it were not written by the same export"*.
 * The browser made neither comparison. It checked the config's `format_version`, that a
 * corpus fingerprint string was present, and the confidence cutoff; and it checked the
 * index's own `format_version`. Nothing tied the two together, so the page could render
 * one bundle's corpus fingerprint, document count and "as of" range over another
 * bundle's passages.
 *
 * The cross-language half matters as much as the check. A digest the port computes
 * differently from Python is a check that fires on every correct bundle, which is worse
 * than no check because somebody deletes it. So the assertion here is not that the TS
 * digest equals another TS digest — it is that the TS digest equals **the string Python
 * wrote into the committed bundle**, which is the only comparison that can catch a
 * canonicalisation disagreement between the two implementations.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  assertBundleDescribesIndex,
  indexChunkIdsDigest,
  type WebConfig,
} from "../src/config.js";
import { indexChunkIds } from "../src/store.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// Compiles to dist/test/, so the package root holding public/data/*.json is two up.
const ROOT = path.resolve(HERE, "..", "..");

function readJson(relative: string): unknown {
  return JSON.parse(readFileSync(path.join(ROOT, relative), "utf8"));
}

function bundle(): { config: WebConfig; index: unknown } {
  return {
    config: readJson("public/data/config.json") as WebConfig,
    index: readJson("public/data/index.json"),
  };
}

test("the port's chunk-id digest is the one Python wrote into this bundle", () => {
  const { config, index } = bundle();
  const ids = indexChunkIds(index);
  const { count, digest } = indexChunkIdsDigest(ids);

  // The floor: a bundle with a handful of chunks would make the comparison below true
  // for reasons unrelated to the digest agreeing.
  assert.ok(count > 50, `only ${String(count)} chunk id(s) read out of the bundle's index`);
  assert.equal(count, config.provenance.index_chunks);
  assert.equal(digest, config.provenance.index_chunk_ids_sha256);
  assert.match(digest, /^sha256:[0-9a-f]{64}$/);
});

test("the committed bundle's config describes the index shipped beside it", () => {
  const { config, index } = bundle();
  assert.doesNotThrow(() => {
    assertBundleDescribesIndex(config, indexChunkIds(index));
  });
});

test("a config paired with a different index is refused, and says which field moved", () => {
  const { config, index } = bundle();
  const ids = indexChunkIds(index);

  // Same count, different passages — the failure a count alone cannot see, and the one
  // that matters: an index of the same size built from a corpus that has moved on.
  const swapped = [...ids];
  const first = swapped[0] as string;
  swapped[0] = first.replace(/^./, first.startsWith("0") ? "1" : "0");
  assert.throws(
    () => {
      assertBundleDescribesIndex(config, swapped);
    },
    /index chunk ids/,
    "an index with the same number of different passages was accepted",
  );

  // Different count — caught by the coarser field, which is the one whose message a
  // reader can act on without hashing anything.
  assert.throws(
    () => {
      assertBundleDescribesIndex(config, ids.slice(1));
    },
    /chunk\(s\) and index\.json holds/,
    "an index with a different number of chunks was accepted",
  );
});

test("an index that cannot be identified is refused rather than digested", () => {
  // Both are states in which every comparison against the id list would be vacuously
  // true. An empty list hashes to a perfectly good digest, which is exactly why the
  // refusal has to happen before the hash rather than after it.
  assert.throws(() => indexChunkIds({ chunks: [] }), /carries no chunks/);
  assert.throws(() => indexChunkIds({ chunks: [{ text: "x" }] }), /chunk_id/);
  assert.throws(() => indexChunkIds({ chunks: [{ chunk_id: "NOT-HEX" }] }), /chunk_id/);
  assert.throws(() => indexChunkIds({}), /carries no chunks/);
});

test("loadAssistant makes the comparison, not just config.ts", async () => {
  // The hole this whole change is about is a check that exists and is not consulted, so
  // asserting the function refuses is not enough — the load path has to call it. Stubbed
  // `fetch` rather than a spy, because that is the seam `loadAssistant` actually uses and
  // it exercises the real ordering: config parsed, index parsed, then the join.
  const { loadAssistant } = await import("../src/index.js");
  const config = readJson("public/data/config.json");
  const index = readJson("public/data/index.json") as { chunks: unknown[]; vectors: unknown[] };
  const shortened = {
    ...index,
    chunks: index.chunks.slice(0, -1),
    vectors: index.vectors.slice(0, -1),
  };

  const realFetch = globalThis.fetch;
  const serve = (body: unknown): Response =>
    new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "text/json" } });
  globalThis.fetch = ((input: RequestInfo | URL) =>
    Promise.resolve(
      String(input).endsWith("config.json") ? serve(config) : serve(shortened),
    )) as typeof fetch;
  try {
    await assert.rejects(loadAssistant("./data/"), /were not written by the same export/);
    // The paired bundle must still load, or this test is satisfied by a loader that
    // refuses everything — which is the stricter-looking wrong implementation.
    globalThis.fetch = ((input: RequestInfo | URL) =>
      Promise.resolve(
        String(input).endsWith("config.json") ? serve(config) : serve(index),
      )) as typeof fetch;
    await assert.doesNotReject(loadAssistant("./data/"));
  } finally {
    globalThis.fetch = realFetch;
  }
});
