# Data Card — Sprout bundled horticulture + toxicity corpus

> **Datasheets for Datasets** (Gebru et al., 2021), all seven sections. Per
> `STANDARDS/AI-EVALUATION-STANDARD.md` §4, this card is a committed artifact regenerated on
> release, not slideware. It documents the *data*; the *model/pipeline* is documented in
> [`model-card.md`](model-card.md).

| Field | Value |
|---|---|
| Dataset name | `sprout-corpus` (bundled reference corpus) |
| Version | tracked with the package SemVer; manifest pinned by content hash |
| License | **CC0-1.0** (public-domain dedication) — see [§ Distribution](#6-distribution) |
| Languages | English (`en`), Spanish (`es`) — mirrored, parity-enforced |
| Size | ~16 common houseplants × {EN, ES} care + toxicity notes |
| Authored by | Chelsea Kelly-Reif |
| Card date | 2026-06-22 |
| Status | **In build.** The on-disk corpus is materialized by `sprout ingest`; this card is the spec the materialized files conform to. |

> [!IMPORTANT]
> **This corpus is illustrative, not authoritative horticulture, and not veterinary or medical
> advice.** Every passage is *original synthetic prose written for this project*. It exists so the
> eval harness — the actual product — has something honest and license-clean to measure. Toxicity
> *status* (toxic / non-toxic to cats, dogs) tracks publicly known ASPCA-style classifications so
> the safety suite exercises real-shaped facts, but the wording is original and **must not be
> relied on for an actual pet-poisoning decision.** For a real ingestion event, contact a
> veterinarian or a poison-control line — the assistant routes there by design.

---

## 1. Motivation

**Why was this dataset created, and for what task?**
Sprout is a retrieval-augmented houseplant-care assistant whose headline artifact is a public
**evaluation harness** (groundedness, safety, calibration, refusal, multilingual). A RAG system and
its eval need a corpus, and that corpus has hard constraints the public web cannot satisfy:

1. **License-clean and redistributable.** The whole project must `pipx install` and `make eval`
   offline with no scraping, no attribution tax, and no risk of redistributing copyrighted
   horticultural text. A bundled corpus that is *authored for the project* and dedicated **CC0-1.0**
   removes that risk entirely.
2. **Dated, cited, and tamper-evident by construction.** Every passage must carry `source_name`,
   `url`, `license`, and `fetch_date` so the assistant can render "based on references as of
   &lt;date&gt;" and the citation guard can resolve each sentence to a passage. Synthetic data lets
   every field be filled deterministically.
3. **A real safety edge without a real-world hazard.** Houseplant toxicity to pets and children is a
   genuine safety property — enough to exercise the never-certify-"safe" guard and poison-control
   routing — while remaining low-stakes, universally legible, and outside anyone's regulated domain.
4. **EN/ES parity testable.** The multilingual suite needs an English passage and its Spanish mirror
   that preserve the same facts and figures; authoring both halves guarantees the mirror exists.

The dataset is *not* intended to teach horticulture, train a model, or substitute for an
authoritative reference. It is a fixture for an eval.

**Who created it and who funded it?**
Authored by Chelsea Kelly-Reif as part of an independent, personal, open-source portfolio project
(Apache-2.0 code, CC0-1.0 data). Unaffiliated with any employer or client; no external funding;
contains no proprietary or client material.

---

## 2. Composition

**What do the instances represent?**
Each instance is a **care note for one common houseplant**, in one language. A note is a small
Markdown document with the H1 title dropped at ingest (the title comes from the manifest) and the
body organized into care-**topic** sections (`## watering`, `## light`, `## soil`, `## humidity`,
`## fertilizing`, `## common problems`, `## toxicity`). `chunk.py` splits each note along those `## `
headings and packs whole sentences into ≤120-word, 24-word-overlap windows, so the retrievable unit
("chunk") is a topic-scoped passage that never ends mid-sentence — required because the offline
generator quotes whole sentences verbatim.

**How many instances are there?**
~16 species × 2 languages = ~32 source notes. Chunking yields a few hundred topic-scoped passages
(the exact count is a function of `chunk.max_words`/`overlap_words` and is fixed for a given config —
content-hashed and reproducible). The species set is the common-houseplant core, e.g.:

| Toxicity posture (ASPCA-style, illustrative) | Example species |
|---|---|
| Toxic to cats and/or dogs | Monstera (*Monstera deliciosa*), Pothos (*Epipremnum aureum*), Philodendron, Snake plant (*Dracaena trifasciata*), Peace lily (*Spathiphyllum*), ZZ plant (*Zamioculcas*), Aloe vera, English ivy |
| Generally non-toxic (per ASPCA-style listing) | Spider plant (*Chlorophytum*), Boston fern, Calathea / prayer plant, Phalaenopsis orchid |

(The exact roster is whatever the committed `corpus/manifest.yaml` enumerates; this table is the
intended composition, not a contract on individual rows. **Planned, not yet in the corpus:**
Dieffenbachia, Areca palm, African violet, Hoya — candidates for a future species-roster expansion;
they are not part of the bundled `corpus/manifest.yaml` today and any question about them correctly
falls to the refusal path.)

> **A "generally non-toxic" listing is not a safety guarantee.** This column tracks an ASPCA-style
> *classification* so the safety suite exercises real-shaped facts — it is **not** a clearance to let
> a pet or child chew the plant. Any plant material can cause vomiting or GI upset, and individual
> animals vary; the assistant never renders a "non-toxic" listing as a "safe" certification (the
> never-certify-"safe" guard) and attaches a non-toxic caveat plus a vet/poison-control escalation
> card to every toxicity answer. The wording here is original and **must not** be treated as
> veterinary ground truth (see the illustrative-only banner above).

**Is each instance complete, or is there missing data?**
By policy, **provenance is never missing**: ingest (`load_corpus`) joins every processed file to a
manifest row and *fails loudly* if a file has no entry, so a passage without `source_name` / `url` /
`license` / `fetch_date` cannot enter the index. Coverage of *horticultural topics*, by contrast, is
deliberately partial — not every species documents every topic — which is intentional, because the
**refusal** and **calibration** suites need genuine corpus gaps to test honest "I don't have a cited
reference for this" behavior and below-threshold abstention.

**What data does each instance contain (the manifest schema)?**
Per `ingest.ManifestEntry` (extra fields forbidden):

| Field | Meaning |
|---|---|
| `file` | path under `corpus/processed/`, the stable citation key (`monstera.md`, `monstera.es.md`) |
| `title` | human-facing title (e.g. "Monstera care") |
| `source_name` | synthetic publisher label |
| `url` | placeholder/synthetic reference URL |
| `license` | `CC0-1.0` |
| `fetch_date` | ISO-8601 snapshot date (e.g. `2026-05-01`) |
| `language` | `en` or `es` |
| `topic` | default care topic for the note (`general` unless overridden) |

**Are there labels?** Yes — the `toxicity` section carries the safety-relevant signal (toxic /
non-toxic to a given animal, with symptoms-as-prose), and the eval datasets (separate from this
corpus, see [`model-card.md`](model-card.md)) carry gold expected-behavior labels that *reference*
these passages.

**Are relationships between instances explicit?** Yes, two:
- **EN↔ES mirror.** `monstera.md` and `monstera.es.md` describe the same plant; the multilingual
  suite parses the species slug from the citation to pair them and asserts the Spanish answer
  preserves the English facts and citations.
- **Same-species topic sections** within a note are related by the `## topic` they sit under and the
  `species/topic` retrieval filter that scopes a query to its named plant.

**Sensitive data / PII / offensive content?**
**None by design.** The corpus is synthetic prose about plants; it contains no personal data, no
human subjects, and no offensive content. The PII story is a *guard* concern, not a corpus concern:
`guards.redact_pii` and the Family-Greenhouse sentinel-PII checks govern the (optional) network path
and household-data path, never this static corpus.

**Errors, noise, redundancies?**
The deliberate near-duplication is the EN/ES mirror and the 24-word chunk overlap; both are
intended. Factual errors are possible (it is synthetic prose) but bounded: the corpus only has to be
*internally consistent enough* for the eval gold key, and any horticultural claim it makes is
explicitly illustrative.

**Is it self-contained?**
Yes. The corpus is committed to the repository under `corpus/` (raw snapshots + processed Markdown +
`manifest.yaml`); it relies on no external resource at run time. The `url` fields are
synthetic/placeholder references, not live fetch targets.

---

## 3. Collection process

**How was the data acquired?**
It was **authored, not collected.** There was no scraping, crawling, survey, sensor, or
third-party acquisition. The author wrote each care note as original synthetic prose, choosing the
species roster from common houseplants and aligning each note's `## toxicity` section to the
*publicly known ASPCA-style* toxic/non-toxic status for cats and dogs so the safety suite tests
real-shaped facts. No ASPCA (or any other) text was copied; only the public, factual
classification was used as a target, and the prose around it is original.

**What mechanisms/procedures were used?**
Hand-authoring in Markdown with the project's section convention, followed by the deterministic
ingest pipeline (`sprout ingest`): glob `corpus/processed/**/*.md` → join to `manifest.yaml` →
`chunk_document` (topic split + word-bounded sentence windows) → embed (`HashingEmbedding`, offline)
→ persist `var/index.json`. Chunk IDs and doc IDs are `sha256`-derived, so the index is reproducible.

**Over what timeframe, and what is `fetch_date`?**
Authored during project build (2026). `fetch_date` is the manifest-declared snapshot date for each
note (e.g. `2026-05-01`); because the source is synthetic and authored, `fetch_date` is the date the
note was *fixed for citation*, surfaced verbatim in the UI as "based on references as of &lt;date&gt;."

**Were individuals involved / was consent needed / ethical review?**
No human subjects, no third-party data, no consent question, no IRB. The only ethical concern is
*misuse as authoritative advice*, addressed by the prominent illustrative-only disclaimer, the
never-certify-"safe" guard, and the poison-control/vet routing in the safety path.

---

## 4. Preprocessing / cleaning / labeling

**Was preprocessing done?**
Yes, all of it deterministic and in-repo:
- **Cleaning / structuring.** Notes are authored directly in the canonical `## topic` Markdown form,
  so cleaning is minimal; the H1 title is dropped at chunk time (the manifest is the title authority).
- **Chunking.** `chunk_document` splits on `## ` headings into `(topic, body)` pairs, slugs the
  topic, and packs whole sentences into ≤`max_words` (120) windows with `overlap_words` (24) of
  sentence-level overlap. No chunk ends mid-sentence — a precondition for verbatim extractive citing.
- **Embedding.** Offline default is `HashingEmbedding` (deterministic, 512-dim); the production seam
  is Bedrock Titan behind a config switch. BM25 lexical scores are computed for hybrid RRF fusion.
- **Labeling.** Toxicity status is encoded as prose in each `## toxicity` section; the assistant
  *quotes* it and the safety guard forbids turning it into a "safe" certification.
- **Structured toxicity table (EXP-09).** `corpus/toxicity.yaml` mirrors the same toxic/non-toxic
  facts as a machine-readable species x animal x severity table, each row carrying its own
  `source_name`/`url`/`license`/`fetch_date` citation exactly like a manifest entry
  (`src/sprout/toxicity.py:ToxicityRow`). It exists for deterministic coverage accounting
  (`sprout toxicity coverage`) and future exposure-type routing (FIX-13) — **it never
  replaces the cited prose as the rendered answer's source of truth.** `sprout toxicity check`
  fails the build if a row disagrees with its document's prose. Every row is `synthetic: true`
  and stays that way — original placeholder data, not a transcription of a real veterinary
  source — until a veterinary toxicologist reviews the schema semantics and every real row's
  intended rendering; see the hard-gate note atop `corpus/toxicity.yaml` and R1.

**Is the raw data saved?**
Yes — `corpus/raw/` holds the committed snapshots and `corpus/processed/` the cleaned Markdown, both
under version control, so the index rebuilds from source via `make ingest` with no mutable state.

**Is the preprocessing software available?**
Yes, it *is* the package: `src/sprout/ingest.py`, `chunk.py`, `text.py`, `providers/` — Apache-2.0,
typed (`mypy --strict`), unit-tested to the ≥90% branch-coverage floor.

---

## 5. Uses

**What is the dataset used for in this repo?**
1. **Grounding the assistant.** It is the *only* source of horticultural fact; every rendered
   sentence resolves to one of its passages or it does not render (groundedness 100% by construction).
2. **Feeding the eval harness.** The five suites (groundedness, safety, calibration, refusal,
   multilingual) author gold cases *against these passages*; the citation/safety/parity checks
   resolve to this corpus.
3. **A swappable reference.** Phase 4 generalizes to a `corpus.yaml` so any care corpus can replace
   this one; this dataset is the worked example.

**What should it NOT be used for?**
- **Not authoritative horticulture.** Do not use it to actually decide how to water, light, or feed a
  real plant; it is illustrative synthetic prose.
- **Not a toxicity authority.** Do **not** use the `## toxicity` sections to decide whether a real
  pet or child is in danger. The status tracks ASPCA-style public classifications for test realism,
  but the prose is synthetic and may be incomplete or wrong. **For a real ingestion event, contact a
  veterinarian or poison-control line** (the assistant routes there and never certifies "safe").
- **Not training data.** It is a retrieval/eval fixture, not a fine-tuning corpus, and is far too
  small and narrow for that.
- **Not a botanical or medical reference** of any kind.

**What could affect future uses (risks, harms, biases)?**
The principal risk is the **authoritativeness illusion**: a cited, dated, confident-looking answer
can read as expert even though the underlying note is synthetic. Mitigations are structural and
documented: the illustrative-only banner here and in the model card, the never-certify-"safe" guard,
mandatory vet/poison-control routing, calibrated abstention below threshold, and the "reference
implementation" banner in the deployed UI. Coverage bias is real and intentional — only common
houseplants, only EN/ES — and an adopter pointing Sprout at a different corpus inherits that corpus's
biases, not this one's.

---

## 6. Distribution

**How is it distributed?**
Bundled inside the open-source Sprout repository and included in built distributions (committed
under `corpus/`), so it is available fully offline. There is no
separate dataset download, API, or hosted endpoint.

**Under what license / IP terms?**
**CC0-1.0** (public-domain dedication) for the dataset, declared per-row in the manifest `license`
field and reiterated in `README.md` and `NOTICE`. CC0 was chosen precisely so redistribution carries
no attribution or share-alike obligation and cannot entangle with the Apache-2.0 code license. The
*code* (including this card's repository) is Apache-2.0; the *data* is CC0-1.0 — two clean licenses,
no conflict. Because the prose is original and synthetic, there are no third-party IP terms, export
controls, or usage restrictions to honor.

**Integrity / tamper-evidence.**
The corpus manifest is content-hashed; eval runs are content-keyed and byte-identical for identical
inputs, so a silent edit to a passage changes the hash and is caught.

---

## 7. Maintenance

**Who maintains it and how are they reached?**
Maintained by the repository owner (Chelsea Kelly-Reif) via the public repository's issues and the
`SECURITY.md` contact. Corpus fixes are **data edits, not code changes** (the "repairability"
attribute): correct the Markdown note, update the manifest `fetch_date` if the content changed, and
re-run `make ingest`.

**Will it be updated, and how are updates communicated?**
Yes, as the species roster and eval suites grow. Updates follow the repository's SemVer + Keep-a-
Changelog discipline; the manifest's per-row `fetch_date` records each note's snapshot date, and the
content hash plus the committed eval report make any change diffable and dated. There is no
push-update mechanism — consumers get a new corpus by upgrading the package, and the assistant always
states the references' as-of date.

**Versioning, deprecation, and older versions.**
The corpus version travels with the package SemVer and the content-hashed manifest; older versions
remain available through the package/Git history (versioned corpus snapshots are an explicit
durability goal). When a passage is corrected, the prior version is preserved in version control,
and the `fetch_date` advances.

**Can others extend / build on it?**
Yes — CC0-1.0 imposes no restrictions, and Phase 4's `corpus.yaml` makes the pipeline corpus-agnostic
so an adopter can drop in their own dated, licensed notes. Contributions are welcome under the
repository's `CONTRIBUTING` guide; any added passage must carry full manifest provenance or ingest
will reject it, so the dated-and-cited invariant survives third-party extension.

---

## References & cross-links

- Gebru et al., *Datasheets for Datasets*, CACM 2021 — the seven-section format this card follows.
- `STANDARDS/AI-EVALUATION-STANDARD.md` §4 — data/model cards as committed, regenerated artifacts.
- `STANDARDS/RESPONSIBLE-TECH-FRAMEWORK.md` §D — transparency-artifact discipline.
- [`docs/cards/model-card.md`](model-card.md) — the pipeline, pinned models, eval results, limits.
- `corpus/manifest.yaml` — the authoritative, dated, per-row provenance this card describes.
- `src/sprout/ingest.py`, `src/sprout/chunk.py` — the ingest/chunk pipeline (the preprocessing software).

*This card is regenerated and re-committed on release. Card date: 2026-06-22.*
