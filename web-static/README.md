# Sprout Static — the deterministic pipeline in the browser, zero server

This is the live reference surface at **<https://sprout.chelseakr.com>**. GitHub Pages
publishes it at the custom-domain root while the MkDocs handbook remains available at
its existing paths such as `/architecture/` and `/audits/eval-report/`.

**EXP-08** (`docs/ideation/03-expansions.md`): a TypeScript port of Sprout's deterministic
stack — hashing embedder, BM25, extractive generator, guards — that runs entirely
client-side over a static, exported `index.json` and `config.json`. No backend, no
telemetry, nothing a question ever leaves this tab for.

## What's here

| Python (`src/sprout/`) | TypeScript (`web-static/src/`) | What it does |
|---|---|---|
| `text.py` | `text.ts` | Tokenize, stem, stop-word/negation filter, sentence split, coverage, jaccard — the shared vocabulary every other module tokenises through. |
| `lexical.py` | `lexical.ts` | Okapi BM25. |
| `providers/deterministic.py`'s `HashingEmbedding` | `sha256.ts` + `hashEmbedding.ts` | SHA-256 token hashing → signed, L2-normalised bag-of-tokens vector. |
| `store.py` | `store.ts` | Flat cosine vector store, loaded from `index.json` (read-only in the browser — there is no ingest path here). |
| `retrieve.py` | `retrieve.ts` | Hybrid dense+BM25 retrieval via Reciprocal Rank Fusion, species/topic filter, near-duplicate dedup, the `min_score` grounding gate. |
| `providers/deterministic.py`'s `ExtractiveGenerator` | `generator.ts` | Verbatim sentence selection by query-token overlap. |
| `guards.py` | `guards.ts` | Citation guard (structural anti-fabrication gate), never-certify-"safe" deny-list, injection detection, PII redaction. |
| `confidence.py` | `confidence.ts` | The ADR-0012 logistic confidence + abstain/low-confidence thresholds. |
| `lang.py` | `lang.ts` | Deterministic EN/ES language detection. |
| `answer.py`'s `Assistant` | `answer.ts` | Orchestrates the above into `.answer(query, language)`. |

`config.ts` types the exported config bundle; `models.ts` types `Chunk`/`Answer`/etc.
`index.ts` is the public entry point: `loadAssistant(dataBaseUrl)` fetches
`config.json` + `index.json` and returns a ready `Assistant`.

The public page shares its visual system with `web/dist/`: `npm run build:site` copies
`web/dist/styles.css` into the generated `web-static/public/` artifact. That keeps the
server-backed development UI and the zero-server public reference from drifting apart.

## Why the data is *exported*, not hand-copied

The algorithms are reimplemented in TypeScript (per EXP-08's own estimate, "all
reimplementable in ~1k lines of TS"), but the *data* they run on — the vector/BM25
index, the guards deny-lists and toxicity keywords, species aliases, per-language
prompt strings — must stay byte-identical to the Python side or the two
implementations silently drift. `scripts/export_web_bundle.py` dumps that data
straight from the loaded, validated `sprout.config.Config` (not by hand-transcription)
to `web-static/public/data/config.json`, and copies the built `var/index.json`
alongside it as `data/index.json`. Both are plain static assets — the only two network
requests the whole assistant ever makes, both same-origin.

## The conformance test — the deliverable's spine

Per EXP-08's own risk assessment: *"dual-implementation drift is the big one — the
conformance test is the deliverable's spine."*

`scripts/generate_conformance_fixtures.py` runs the real Python `Assistant` over every
question in `eval/suites/*.yaml` — the same 142-case set (groundedness, safety,
refusal, calibration, multilingual EN+ES) the Python eval harness scores against — and
records the answer text, citations, confidence, refusal reason, and safety notice to
`web-static/test/fixtures/conformance.json`. `web-static/test/conformance.test.ts`
replays every one of those questions through the TypeScript port loaded from the same
exported bundle and asserts the two implementations agree exactly. It is wired into CI
(`.github/workflows/ci.yml`'s `web-static` job) as part of the required `ci-gate`, so a
port/pipeline change that breaks parity fails the PR, not a later release.

## Building and testing locally

```sh
# From the repo root: build the Python index, then export it + generate fixtures.
make ingest
make web-static-bundle      # -> web-static/public/data/{index,config}.json
make web-static-fixtures    # -> web-static/test/fixtures/conformance.json

cd web-static
npm ci
npm test                    # compiles TS, runs the 142-case conformance test (node:test)
npm run build:site          # compiles + copies dist/src/*.js into public/assets/
python3 -m http.server 8080 --directory public   # or any static file server
```

Then open `http://localhost:8080/`.

## Scope: what this ships versus what's deferred

EXP-08's full shape has four parts. This change delivers (a) and half of (b)/(c); the
rest is real follow-up work, not claimed here:

- **(a) Algorithm port + conformance test — done.** All five deterministic modules
  ported, 142/142 fixture cases passing, wired into CI.
- **(b) Index + locales as static assets with subresource integrity — partial.** The
  data assets are exported and fetched statically; **SRI hashes are not yet wired into
  `index.html`** (there is no build-time hash-and-rewrite step here).
- **(c) Installable offline PWA — a minimal version.** A `manifest.webmanifest` and a
  cache-first service worker are included and were smoke-tested against a real static
  HTTP server. **`manifest.webmanifest`'s `icons` array is empty** — there are no
  designed app icons in this repo to ship honestly, and Lighthouse's PWA installability
  check will fail without them. The deployed HTML is covered by Sprout's structural
  accessibility gate. A dedicated browser-based WCAG 2.2 AAA / Lighthouse a11y+perf
  ≥ 0.95 audit of this zero-server route remains follow-up work.
- **(d) The never-certify-safe deny-list and escalation card ship in the bundle —
  done**, via the exported `config.json`'s `guards`/`prompts` sections (same source of
  truth as the Python side, not a second hand-authored copy).
- **(e) Continuous deployment — done.** `.github/workflows/pages.yml` rebuilds the
  corpus bundle and TypeScript modules on every push to `main`, overlays the resulting
  `web-static/public/` artifact onto the MkDocs site, and deploys the combined site to
  `sprout.chelseakr.com` through GitHub Pages.

## Non-goals (by design, matching the Python original)

- No cloud generator path (`bedrock`/`anthropic` `generation.provider`) — the browser
  port only implements the offline deterministic path; `export_web_bundle.py` refuses
  to export a bundle configured for a non-`deterministic` embedding provider.
- No photo identification or reminders in the demo page — both need either network
  egress or local-storage wiring this change does not add. Type the plant's name
  instead, exactly as the Python CLI's fallback does.
