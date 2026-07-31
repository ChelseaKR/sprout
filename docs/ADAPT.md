# Adapt Sprout to your domain

> Sprout's houseplant corpus is a **worked example**, not the product. The product is the
> pipeline (guards → retrieve → extractive generate → citation guard → confidence) and the
> public evaluation harness that holds it to account. Both are corpus-agnostic. This guide
> walks through replacing the bundled plant-care corpus with your own cited domain — recipes,
> internal runbooks, a product FAQ, another care domain entirely — using only the existing
> config seam.

## Overview

The **only file an adopter edits is `config/sprout.yaml`**. Every config model forbids unknown
keys (`extra="forbid"` — see `src/sprout/config.py`), so a misspelled or invented key fails
loudly at load time instead of silently falling back to a default. Secrets — API keys, cloud
regions used as credentials context — are **never** stored in the config; they are read from
the environment (the `PLANTNET_API_KEY` pattern below is the template for any provider you add).

The eval runner (`sprout eval`) and the retrieval/generation pipeline (`retrieve.py`,
`generate.py`, `ingest.py`, `chunk.py`) contain no plant-specific logic. They operate on
whatever `corpus.path` + `corpus.manifest` point at. Swapping domains is a **data and config**
change, not a code change — with one exception: the eval **suites** under `eval/suites/` encode
plant-care questions and expected facts, and you will need to re-author those for your domain
(Step 8).

This guide is organized as the steps an adopter takes, in order, each naming the real
`config/sprout.yaml` key(s) it touches.

---

## Step 1 — Prepare your corpus

Drop cleaned, chunked-ready Markdown passages under a directory — the default is
`corpus/processed`, matched by `corpus.glob: "**/*.md"`. Aim for **one topic per file** (e.g.
one file per plant species in the bundled corpus; one file per recipe, per product, or per
runbook in yours). Sprout's chunker (`chunk_document` in `src/sprout/chunk.py`) splits each file
on `## ` headings into `(topic, body)` pairs, so structuring a file with `##`-level topic
sections gives you free per-topic retrieval scoping later (`retrieval.topic_filter`, Step 4).

Within each topic section, `chunk_document` packs whole sentences into fixed-size windows so a
chunk never ends mid-sentence — a precondition for the citation guard, which quotes verbatim
(Step 5). Window sizing is controlled by two `chunk.*` keys:

```yaml
chunk:
  max_words: 120     # upper bound on words per chunk
  overlap_words: 24   # sentence-level overlap between consecutive chunks
```

Keep `max_words` large enough that a topic section's key fact survives in one chunk, and
`overlap_words` large enough that a fact near a chunk boundary isn't orphaned from its context.
120/24 (a 20% overlap) is the bundled corpus's tuning for short care notes; a domain with longer
prose (e.g. long-form runbooks) may want a larger `max_words`.

## Step 2 — Write the manifest (`corpus/manifest.yaml`)

Every processed file must have a corresponding entry in the manifest, or `sprout ingest` fails
loudly rather than silently indexing an unprovenanced passage (`ingest.ManifestEntry`, extra
fields forbidden). The bundled `corpus/manifest.yaml` shows the required per-document shape:

```yaml
documents:
- file: aloe.md                          # path under corpus.path — the citation key
  title: Aloe vera care                  # human-facing title (H1 is dropped at chunk time)
  language: en                           # must be in languages.supported
  source_name: Synthetic Plant-Care Notes
  url: https://example.invalid/aloe
  license: CC0-1.0
  fetch_date: '2026-05-01'               # ISO-8601 snapshot date
  topic: care                            # default topic for the note
```

**Licensing/provenance discipline is not optional.** Every cited source needs a `license` and a
`fetch_date` — this is what lets Sprout render "based on references as of &lt;date&gt;" and lets
the citation guard resolve a rendered sentence back to a real, dated, licensed passage. If you
adapt Sprout to a domain with real (non-synthetic) sources, `license` must reflect the actual
terms you have to redistribute or reference that text under, and `url` should point at the real
source rather than a placeholder.

If you follow the bundled corpus's precedent of authoring **original, synthetic** passages
(rather than ingesting real third-party text) so the whole project stays offline-installable and
redistribution-clean, write a data card documenting that choice the way
[`docs/cards/data-card-corpus.md`](cards/data-card-corpus.md) does for the plant-care corpus —
motivation, composition, collection process, and known limitations, per the Datasheets-for-
Datasets structure it follows. That data card is the precedent to copy, not a file this guide
generates for you.

## Step 3 — Point config at your corpus

Four `corpus.*` keys wire the pipeline to your directory and manifest:

```yaml
corpus:
  path: corpus/processed          # where your chunked Markdown lives
  glob: "**/*.md"
  manifest: corpus/manifest.yaml  # your manifest from Step 2
  default_language: en            # must be first in languages.supported (Step 6)
```

None of these have to point inside this repository's `corpus/` directory specifically — `path`
and `manifest` are ordinary filesystem paths relative to the config file's working directory.

## Step 4 — Domain vocabulary

Two `retrieval.*` keys generalize beyond "plant species" to **any entity-scoped corpus** — a
recipe corpus keyed by dish, a runbook corpus keyed by service name, a product-FAQ corpus keyed
by SKU:

```yaml
retrieval:
  topic_filter: true       # scope retrieval to the named entity when the question names one
  species_aliases:         # alternate/foreign-language name -> corpus slug
    potos: pothos
    "lengua de suegra": snake-plant
    ...
```

`species_aliases` (the key name is a holdover from the plant-care domain; it is not renamed by
this seam) maps any alternate name a user might type — a synonym, an abbreviation, a translated
name — to the canonical slug your corpus files and manifest use for that entity. `retrieve.py`'s
`_named_species` matches on accent-folded, stemmed tokens against both the raw entity slugs and
this alias map, so a query naming an entity by any of its aliases gets scoped to that entity's
passages when `topic_filter` is on. For a non-plant domain, populate this map with your domain's
synonyms (e.g. `"laptop won't boot": boot-failure` for a runbook corpus) rather than deleting it.

## Step 5 — Tune retrieval/abstention for your domain

Retrieval ranking and dedup:

```yaml
retrieval:
  top_k: 6                # chunks retrieved before dedup/rerank
  min_score: 0.12          # below this, refuse rather than pad the answer
  hybrid: true              # fuse dense + BM25 via reciprocal rank fusion (RRF)
  rrf_k: 60                 # RRF smoothing constant
  dedup_threshold: 0.92     # near-duplicate chunks above this similarity are collapsed
```

Generation and the citation guard:

```yaml
generation:
  relevance_floor: 0.30     # a candidate chunk below this relevance is dropped pre-generation
  support_overlap: 0.66     # citation guard: a rendered sentence must be this covered by its
                              # source chunk, or it is not rendered
  max_sentences: 3           # cap on sentences per answer
```

Confidence and abstention:

```yaml
confidence:
  abstain_threshold: 0.25         # below this computed confidence, refuse rather than guess
  low_confidence_threshold: 0.50  # below this, answer but flag for human review
```

**Sprout's design bias is fail-closed.** `min_score`, `relevance_floor`, `support_overlap`, and
`abstain_threshold` all exist to make the system refuse — or flag — rather than fabricate. When
you first point Sprout at a new corpus, expect a higher refusal rate than you want; the correct
fix is almost always to **add more corpus coverage** (Step 1–2) for the gaps the refusals are
pointing at, not to loosen these thresholds until fabrication risk creeps back in. If your
domain has real safety stakes (medical, legal, financial, safety-critical operational
guidance), keep these thresholds conservative and read `docs/THREAT-MODEL.md` and
`docs/adr/0004-never-certify-safe-output-guard.md` before tuning them down.

## Step 6 — Languages

```yaml
languages:
  supported: [en, es]   # first entry is the parity reference language
```

Add or remove language codes here. `languages.reference` (the first entry) is the language every
other language's answers are checked against for **fact parity** by the multilingual eval suite
— so pick the language you have the deepest, most complete corpus coverage in as the first
entry.

Per-language corpus files follow the bundled convention of a language suffix before `.md` (e.g.
`monstera.md` for English, `monstera.es.md` for Spanish) — both entered separately in the
manifest with their own `language` field. If you support only one language, drop the second
entry from `supported`; the parity suite (`eval/suites/multilingual.yaml`, checked by
`src/sprout/eval/suites/multilingual.py`) only exercises languages present in your corpus and
suite cases, so a single-language deployment simply has no multilingual pairs to check.

## Step 7 — Swap the generator/embeddings (optional, network)

By default Sprout runs fully offline: a deterministic extractive generator and a deterministic
hashing embedder, so `make ingest`/`make eval` need no cloud account. Two provider keys switch
each side independently:

```yaml
retrieval:
  embedding_provider: deterministic   # deterministic (offline) | bedrock (Titan)

generation:
  provider: deterministic             # deterministic (extractive) | bedrock | anthropic
  # model: anthropic.claude-haiku-4-5-20251001-v1:0   # provider: bedrock
  # model: claude-haiku-4-5-20251001                  # provider: anthropic (native)
  region: us-west-2                   # cloud region, not a secret
  max_cost_usd: 0.05                  # per-answer preflight ceiling; unpriced models refuse
  redact_query_pii: false             # redact PII before sending a query to a network provider
```

`generation.model` is provider-specific: Bedrock uses an `anthropic.*` model id or supported
inference profile; the native API uses a `claude-*` id. Cloud-provider activation rejects crossing
those namespaces and any id absent from the pinned price table. Set the Bedrock model explicitly:
the legacy constructor fallback is unpriced and intentionally fails closed. The operational
wrapper estimates cost before every transport call and returns no candidates when the estimate
exceeds `max_cost_usd`, so the normal answer pipeline refuses.

Titan embedding pricing is exact and region-aware: `amazon.titan-embed-text-v2:0` uses the AWS
catalog row for `generation.region`, which Sprout carries into the shared `Usage` record. A missing
or unsupported region fails activation rather than borrowing another region's rate; unsupported
output/cache usage for this input-only model is likewise unpriceable. Sprout does not fork or
override the portfolio-owned price table locally.

`generation.region` is deployment context, not a credential, and is safe to commit. **API keys
are never config values.** Follow
the `PLANTNET_API_KEY` pattern used by the photo-identification provider
(`src/sprout/providers/plantnet.py`): the key is read from an environment variable of the same
shape (`os.environ.get("...")`) at call time, with no key material ever written to
`config/sprout.yaml` or committed anywhere. If you wire up Bedrock or the native Anthropic
provider, your cloud credentials follow the standard AWS/Anthropic SDK environment-variable or
credential-file conventions — again, never the Sprout config file.

## Step 8 — Rebuild and validate

```sh
make ingest   # glob corpus.path -> join to corpus.manifest -> chunk -> embed -> var/index.json
make eval     # run the eval suites against your corpus, regenerate docs/audits/eval-report.*
make verify   # full local gate set: lint · type · test · security · eval · a11y
```

`make ingest` rebuilds the index from your corpus and manifest — rerun it any time you edit a
corpus file, add a document, or change `chunk.*`/`corpus.*` config. `make eval` then runs the
five eval suites (groundedness, safety, calibration, refusal, multilingual) against the rebuilt
index and regenerates the committed eval report.

**The eval suites under `eval/suites/` (`groundedness.yaml`, `safety.yaml`, `calibration.yaml`,
`refusal.yaml`, `multilingual.yaml`) are written against the bundled plant-care corpus and must
be re-authored for your domain.** Each case names a question, an `expected_behavior`
(`answer`/`refuse`), and either `expected_facts` or `must_mention` keyed to specific passages in
*this* corpus — none of that transfers to a different domain. Use the bundled suites as a
template for shape and coverage (a groundedness case per key fact, a safety case per hazard your
domain has, a refusal case per deliberate corpus gap, a calibration probe set, and an EN/ES —
or your language pair's — parity case per fact if you support multiple languages), but write new
cases against your own corpus's passages.

`make verify` is the full local mirror of the CI gate set and the bar every phase of this
project is held to — if it is not green, the adaptation is not done.

---

## A note on framing

The bundled plant-care corpus carries a **"reference implementation, not authoritative
horticulture"** banner throughout the docs (see [`docs/index.md`](index.md) and the
[data card](cards/data-card-corpus.md)) precisely because a cited, dated, confidently-formatted
answer can *read* as authoritative even when the underlying corpus is illustrative. Carry the
equivalent framing into your domain: state plainly, in your own UI and docs, what your corpus is
and is not authoritative for, and keep the never-fabricate, fail-closed posture (Step 5) as the
non-negotiable core, even as you swap out every fact underneath it.
