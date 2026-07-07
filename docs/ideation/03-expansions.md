# Expansions — EXP-01 … EXP-17 (drafted 2026-07-01)

Three horizons: **H1** deepen the core, **H2** adjacent capabilities/audiences/
integrations, **H3** transformative bets. Nothing here restates an E-item from
[`../RESEARCH-ROADMAP.md`](../RESEARCH-ROADMAP.md); overlaps are called out with the
delta. Effort tiers as in [`02-large-scale-fixes.md`](02-large-scale-fixes.md).

---

## H1 — Deepen the core

### EXP-01 — Facet-coverage answer planner + a "completeness" metric

**Pitch.** Teach the extractive generator to *cover the question*, not just to rank
sentences — and measure completeness as a first-class eval metric.

**Impact.** The model card names "correct-but-contextually-incomplete" as the residual
that matters most; today `ExtractiveGenerator.generate` (providers/deterministic.py)
ranks sentences independently by query-token overlap, so a two-part question ("how often
should I water, and does that change in winter?") can return three near-duplicate
watering sentences and miss the seasonal clause entirely. Persona A1's trust hangs on
exactly this.

**Shape.** (a) Facet extraction from the query (topic keywords → the corpus's own
`## topic` taxonomy carried on every `Chunk.topic`); (b) greedy selection with a
diversity term: next sentence maximizes marginal facet coverage, still verbatim, still
per-chunk-tagged, so `citation_guard` is untouched; (c) a deterministic `completeness`
check in the eval (fraction of authored `expected_facts` facets covered per case), added
to `eval/suites/groundedness.yaml` cases that already carry multiple facts.
**Effort:** M. **Risks/deps:** more sentences ≠ better answers — cap at
`generation.max_sentences`; validate answer-shape change with real users (A1 walk-risk).
**Excellence bar:** multi-facet cases pass at ≥ 0.9 completeness with zero groundedness
regression; answers stop repeating the same fact twice.

### EXP-02 — Source-disagreement surfacing ("the references differ")

**Pitch.** When retrieved passages conflict, say so with both citations, instead of
silently rendering whichever ranked first.

**Impact.** The repo's founding observation is that "plant-care lore is contradictory
and seasonal" (CLAUDE.md), yet the pipeline has no concept of disagreement — top-ranked
wins. Surfacing conflict is the honesty ethos extended from "cite or refuse" to "cite,
and disclose dissent." Directly serves B2 (SME correctness) and C2 (method credibility).

**Shape.** (a) A pairwise contradiction probe across surviving `AnswerSentence`s and
their sibling chunks using the machinery that already exists (`text.has_negation`,
polarity comparison from `guards._supported_by`, numeric-value extraction for
"every 7 days" vs "every 14 days" clashes); (b) when triggered, render a localized
"sources differ on this point" block carrying both citations — never averaging, never
choosing; (c) an eval slice with authored conflicting passages in a test corpus.
**Effort:** M. **Risks/deps:** naive polarity checks over-fire (seasonal qualifiers are
legitimate differences, not contradictions) — start with numeric-cadence conflicts only;
copy is user-facing but not safety copy (still route toxicity conflicts to the existing
safety path, where disagreement between sources must *always* surface conservatively).
**Excellence bar:** on a seeded-conflict corpus, ≥ 0.9 of true conflicts surfaced,
≤ 0.05 false-conflict rate; toxicity conflicts always resolve to the more conservative
rendering plus routing.

### EXP-03 — Offline *semantic* embedding provider (deterministic static vectors)

**Pitch.** A third `EmbeddingProvider`: pre-computed static word/subword vectors shipped
as versioned data — semantic recall without network, nondeterminism, or a cloud account.

**Impact.** The committed report holds refusal at 0.90 explicitly because "the hashing
embedder cannot fully separate every unknown-species or jailbreak phrasing" — the
offline default trades recall for reproducibility. A static-embedding table (model2vec
/ word2vec-style lookup, L2-normalized, summed) is *also* fully deterministic, closing
part of that gap while preserving the entire offline story. Could lift refusal and
retrieval quality enough to retire the 0.90 deviation (ties to FIX-01's ledger
reconciliation).

**Shape.** (a) `providers/static_embedding.py` implementing the existing
`EmbeddingProvider` Protocol; (b) a curated, license-clean vector table for the
plant-care vocabulary (EN+ES), shipped like corpus data with provenance in a manifest;
(c) ADR with the eval delta — the house rule ("no reranker/upgrade without an ADR
justifying an eval delta") applies verbatim; (d) re-fit confidence after (FIX-08).
**Effort:** L. **Risks/deps:** vector-table licensing and size (keep ≤ a few MB by
vocabulary restriction); ES coverage of the table must be verified or the parity gate
regresses. **Excellence bar:** refusal ≥ 0.95 offline with groundedness unchanged at
1.000; eval remains byte-identical for identical inputs.

### EXP-04 — NLI-grade entailment verifier for the cloud path

**Pitch.** Build the control the model card already prescribes for production: a real
entailment check behind `citation_guard` when the generator is Claude.

**Impact.** The model card states: "A production deployment should add an NLI-grade
entailment verifier on the cloud path; the guards are the safety boundary, not the
model's instruction-following." No backlog item exists for it. Lexical coverage +
polarity (`guards._supported_by`) admits same-plant recombination — FIX-05 will quantify
it; this expansion eliminates most of it.

**Shape.** (a) A small cross-encoder NLI model (ONNX, CPU, pinned weights hashed into
the run identity like the judge config) as an optional `support_verifier: nli` config;
(b) applies only when `generation.provider != deterministic` — the offline path keeps
its by-construction guarantee and zero-dependency install; (c) the verifier's
threshold and version go into the eval fingerprint; (d) ADR (guarded file).
**Effort:** L. **Risks/deps:** model weights are a new supply-chain artifact (hash-pin,
SBOM); latency on the cloud path grows (acceptable — that path is already networked);
NLI models are EN-strong/ES-weaker — measure per-language before claiming parity.
**Excellence bar:** FIX-05's measured recombination admit-rate drops ≥ 10× on the cloud
path; offline behavior bit-identical to today.

### EXP-05 — Explicit season/context qualifiers (user-stated, selector-only)

**Pitch.** Let the user state season and placement ("winter, north window") and use it
to *select* the governing passage — the same contract as photo-ID: context selects,
corpus asserts.

**Impact.** Seasonality is the canonical grounding trap the corpus already encodes
(every care file has winter guidance; e.g., `corpus/processed/pothos.md` watering
section). Today a winter question depends on lexical luck. ADR-0010's selector-not-fact
pattern generalizes cleanly, and nothing is inferred about the user.

**Shape.** (a) Optional `--season/--light` CLI flags and UI selects, mapped to retrieval
boosts for sentences containing the corresponding corpus vocabulary (no new metadata
needed initially — the prose already qualifies); (b) the qualifier is echoed in the
answer header as user-provided context, never as a cited fact; (c) eval cases pairing
the same question ± season asserting the seasonal sentence is selected.
**Effort:** M. **Risks/deps:** hemisphere ambiguity — take "winter" as the user's word,
never derive from locale/clock (privacy + honesty); scope-creep risk toward a profile
(explicitly rejected — per-request only, consistent with the no-user-model stance in
RESPONSIBLE-TECH-AUDITS §B). **Excellence bar:** seasonal eval slice ≥ 0.95 correct
passage selection; zero persistent user state added.

### EXP-06 — Verbalized, screen-reader-first uncertainty bands

**Pitch.** Turn the calibrated number into calibrated *language*: "well-supported" /
"partially supported — verify" bands derived from the reliability diagram, announced
accessibly.

**Impact.** `Answer.confidence` renders as a raw float (`cli._print_answer_obj`,
`web/dist/app.js` meta line). Raw probabilities are poorly read by lay users and
screen-reader flows; the reliability data to justify honest bands already exists
(`confidence.reliability_diagram`). Serves A1/D1 without touching thresholds. Distinct
from R8 (photo-ID uncertainty surfacing): this is the *care answer's* confidence.

**Shape.** Band cut-points derived from the committed reliability bins (not invented),
localized strings in the FIX-09 bundles, `aria` semantics in the UI, band + float both
shown (never hide the number). **Effort:** S–M. **Risks/deps:** bands must be re-derived
when FIX-08 re-fits; wording is trust-sensitive → include in the release
representational review. **Excellence bar:** each band's realized accuracy in the eval
matches its label ±10 pp, verified per release.

---

## H2 — Adjacent capabilities, audiences, integrations

### EXP-07 — Grounded multi-turn: history as a selector, never a source

**Pitch.** Follow-ups ("what about in winter?", "¿y para los perros?") resolve species/
topic from conversation history under the selector-not-fact contract — the designed
replacement for the phantom `session_memory` (FIX-11).

**Impact.** Single-shot Q&A forces users to restate the plant every turn; every real
chat products' first friction. The grounding risk (history smuggling facts) is exactly
what Sprout's provenance architecture is built to control.

**Shape.** (a) A bounded, in-memory-only turn window (the `session_memory` semantics,
actually implemented this time) keyed by an opaque session id, holding only
{species-slug, topic, language} — never answer text; (b) anaphora resolution merges the
prior slug into `Retriever`'s species filter; (c) a new `conversation` eval suite:
follow-up correctness, plus adversarial cases where history tries to override a cited
fact (must lose); (d) DPIA row added *with* the feature (the audit-before-feature
pattern §C already stages for Family Greenhouse).
**Effort:** L. **Risks/deps:** server statelessness claim changes → FIX-11 first, DPIA
concurrently; CLI stays single-shot. **Excellence bar:** follow-up suite ≥ 0.95; a
history-injection case can never alter which chunks ground an answer, proven by trace.

### EXP-08 — Sprout Static: the whole pipeline in the browser, zero server

**Pitch.** Port the deterministic stack (hashing embedder, BM25, extractive generator,
guards) to JS/WASM over the exported `index.json`, and ship the entire assistant as a
static site — no backend, no telemetry, nothing leaves the device even in web mode.

**Impact.** R4 wants the UI behind a real URL; the strongest possible version of that is
a URL with **no server to trust**: hosting-cost zero forever (the sustainability
attribute CLAUDE.md prizes), the privacy story becomes absolute, and the PWA/offline
aspiration in CLAUDE.md's quality-attribute list gets a real implementation. Also a
uniquely legible demo of "grounding by construction" — reviewers can read the entire
inference path in devtools.

**Shape.** (a) The algorithms are deliberately simple (SHA-256 token hashing, BM25,
token-set overlap — all reimplementable in ~1k lines of TS) — port with a cross-language
conformance test asserting identical answers to the Python pipeline over the full eval
question set; (b) index + locales fetched as static assets with subresource integrity;
(c) service worker for installable offline PWA; (d) the never-certify-safe deny-list and
escalation card ship in the bundle (same FIX-09 locale data). Photo-ID stays fallback-only
(no egress from a static page by default).
**Effort:** XL. **Risks/deps:** dual-implementation drift is the big one — the
conformance test *is* the deliverable's spine; WCAG gates apply to the new surface;
safety copy identical byte-for-byte with the Python bundles.
**Excellence bar:** 100% answer-identical to Python on all eval cases; Lighthouse
a11y/perf ≥ 0.95; deployable from a tag by CI to static hosting.

### EXP-09 — Structured toxicity data model (species × animal × severity, per-row cited)

**Pitch.** Alongside prose passages, a machine-readable toxicity table — each row
carrying its own source/license/fetch-date — powering deterministic coverage accounting,
exposure-type routing (FIX-13), and eventually the real-corpus import.

**Impact.** Today toxicity is prose in a `## Toxicity` section (chunk topic slug is the
only structure). A schema makes three things possible that prose cannot: exact coverage
accounting against an authority list (deeper than E1's eval slice — E1 asserts
citations exist; this knows *which* species/animal pairs are covered), deterministic
rendering of severity-appropriate framing, and a lossless target for importing real
ASPCA-style data when the SME gate opens (R1).

**Shape.** (a) `corpus/toxicity.yaml` schema: species-slug, animal, toxic (bool per the
cited source), principle, severity-class, source row (name/url/license/fetch_date);
(b) ingest validates every row against the manifest discipline (`ingest.load_corpus`
pattern); (c) rendered *answers remain extractive from prose* — the table drives
routing, coverage reports, and the "the cited reference lists/does not list" framing
selection, never free-composed sentences; (d) the eval gains a deterministic
table-vs-prose consistency check (a prose passage contradicting the table fails ingest).
**Hard gates:** synthetic rows only until a veterinary toxicologist reviews the schema
semantics *and* every real row's rendering; the "non-toxic ≠ safe" caveat renders on
every row-driven answer including — especially — "not listed as toxic" rows.
**Effort:** L. **Risks/deps:** severity classes are clinical judgments → SME-owned
vocabulary; dual-representation (prose+table) can drift → the consistency check is
mandatory, not optional. **Excellence bar:** coverage report can name every
species×animal pair the corpus covers, with a citation per cell; zero table-prose
contradictions; SME sign-off artifact committed before any real data lands.

### EXP-10 — Reminders → standards-based export (ICS), still local-first

**Pitch.** `sprout remind export --ics` emits an iCalendar file with RRULEs so reminders
appear in any calendar app — utility without adding sync, push, or accounts.

**Impact.** ADR-0011 honestly scopes reminders to one local JSON file; R9 commits to
*stating* the no-sync limit. Export is the capability that makes the limit livable:
the user's own calendar becomes the notifier, and Sprout still holds no channel to
anyone. **Shape.** Pure function from `ReminderStore.all_reminders()` to RFC 5545 text
(`RRULE:FREQ=DAILY;INTERVAL=n`), deterministic UIDs from `reminder_id`, a UI download
button; no import path (one direction, no state merge). **Effort:** S.
**Risks/deps:** none material — no network, no new state. **Excellence bar:**
round-trips into Apple/Google/Thunderbird calendars correctly in both languages;
reminder JSON remains the single source of truth.

### EXP-11 — On-device photo-ID provider for corpus species

**Pitch.** A `provider: local` identifier — a small quantized classifier over exactly
the corpus's species — so the photo path works offline with zero egress, keeping
Pl@ntNet as the broader-coverage opt-in.

**Impact.** Today `OfflineIdentifier` always falls back (ADR-0010 keeps "offline by
default" honest), so the default experience of the most-requested feature is "type the
name." A ~16–100-class model is a tractable, honest middle: useful, private, and
label-scoped to plants Sprout can actually ground. Goes beyond E8/R8 (which surface
uncertainty for the *existing* providers).

**Shape.** (a) Train/quantize a small classifier (ONNX, CPU) on openly-licensed images
of corpus species; (b) implement the existing `PlantIdentifier` Protocol; same
`min_confidence` + selector contract, same fallback; (c) publish a per-species accuracy
table in the model card — including the confusion pairs — before enabling by default;
(d) extend the §C data inventory: photo bytes now touch a local model (still never
persisted, never egress). **Effort:** XL. **Risks/deps:** image licensing and dataset
documentation (a data card for the training set — real-data gate); accuracy claims need
a held-out test set, not vibes; wheel-size discipline (model as an optional extra,
like `[identify]`). **Excellence bar:** measured top-1 ≥ 0.85 on held-out corpus-species
photos with the confusion matrix published; default install size unchanged (extra
opt-in); ADR-0010's contract untouched.

### EXP-12 — Corpus workbench: growth tooling for a 10× corpus

**Pitch.** Maintainer tooling that makes corpus growth safe: per-species×language×topic
completeness matrix, EN/ES parity diff, chunk-quality lint, and a gap report emitted at
ingest.

**Impact.** Every stakeholder thread (USER-RESEARCH theme 5) converges on the corpus as
bottleneck. E5 (RESEARCH-ROADMAP) designs the *SME contribution* path; this is the
complementary *maintainer QA* layer that keeps quality flat as volume grows — e.g., the
extraction-safety property visible in the current corpus (nearly every sentence names
its plant, which is what makes verbatim extraction unambiguous) is currently an
unwritten convention `scripts/_materialize_content.py` happens to produce.

**Shape.** (a) `sprout corpus-report`: matrix of species × topic × language vs a target
list, emitted as a committed artifact beside the eval report; (b) lint rules at ingest:
sentence length bounds (chunker packs whole sentences ≤ `chunk.max_words`),
plant-name-per-sentence heuristic, mirrored-file structural parity (same `##` sections
EN/ES); (c) a parity diff that flags when an EN edit isn't mirrored in `.es.md`.
**Effort:** M. **Risks/deps:** heuristics advisory at first (REVIEW), promoted to
AUTO-gate once tuned; complements FIX-06 (single-copy) and E5. **Excellence bar:**
a contributor PR adding a species fails CI unless both languages, all target topics, and
the manifest row are present and lint-clean.

### EXP-13 — Eval trend ledger: score history across releases

**Pitch.** Persist every release's `RunResult` and render trends (per-suite score,
n, CI) in the report — catching slow drift that a single baseline diff cannot see.

**Impact.** `diff_against_baseline` (once wired, FIX-02) compares against *one* pinned
run; a metric can decay 1 pp per release under tolerance forever. C1/C2 both trust
trajectories over snapshots. **Shape.** (a) Append per-release fingerprint+scores to
`docs/audits/eval-history.jsonl` in the release workflow; (b) `report.py` renders a
trend table + accessible sparkline (data table equivalent, per the a11y commitments);
(c) a drift rule: k consecutive declines on any suite fails the release gate even inside
tolerance. **Effort:** M. **Risks/deps:** FIX-02 first; history file only appends at
release (not per-PR) to stay deterministic. **Excellence bar:** three releases in, the
report shows per-suite trajectories and the drift rule has a test proving it fires.

### EXP-14 — The harness as a reusable package with a plugin suite API

**Pitch.** Give `sprout.eval` the entry-point plugin architecture CLAUDE.md already
gestures at ("new eval suites via entry points") and prove corpus-agnosticism with a
worked second-domain adaptation.

**Impact.** ADR-0006 chose in-repo for good reasons; the reuse story ("the eval runner
is corpus-agnostic") is currently asserted, not demonstrated — suites self-register at
import time inside the package (`eval/suites/__init__.py`), so a third party cannot add
one without forking. E11 writes the *guide*; this builds the *seam* and a measured
proof. Portfolio leverage: sibling eval-shaped repos could consume the same runner.

**Shape.** (a) `importlib.metadata` entry-point discovery (`sprout.eval.suites` group)
alongside the built-in registry, fail-closed on duplicate names; (b) freeze the public
API surface (`Dataset`, `Judge`, `SuiteResult`, `MetricDefinition`) with semver
commitment; (c) a worked example: a small second corpus in a different care domain
(e.g., succulent-specific or herb-garden notes) evaluated end-to-end with its own
committed numbers, living under `examples/`. **Effort:** L. **Risks/deps:** public-API
freeze constrains refactors (do after FIX-02/12 settle); example corpus must meet the
same manifest/provenance bar. **Excellence bar:** an external package can `pip install
sprout` + register a suite with zero fork; the example's eval report is committed and
reproducible.

---

## H3 — Transformative bets

### EXP-15 — Signed corpus registry: cited corpora as verifiable artifacts

**Pitch.** Define a corpus bundle format (passages + manifest + toxicity table +
content hash) that is signed (Sigstore) and versioned, so third parties — extension
services, SMEs — can publish corpora Sprout verifies before ingesting.

**Impact.** The endgame of "the corpus is the bottleneck and the moat": today the only
trustworthy corpus is the one in this repo. A verification-first distribution channel
turns Sprout from "an assistant with a corpus" into "a runtime for *any* cited care
corpus" — with tamper-evidence extended across the trust boundary. Builds on the
existing content-hash discipline (`dataset.py` sidecar pattern, `determinism.py`) and
the release pipeline's cosign/SLSA posture, and goes well beyond E5 (single-repo
contribution) and E11 (adaptation guide).

**Shape.** Bundle spec (schema-versioned tarball: manifest, processed files, optional
toxicity table, `suites/` cases, sha256 tree); `sprout corpus verify|install <bundle>`
enforcing signature, license allowlist, and manifest completeness before anything is
readable by ingest; provenance of the *publisher* recorded in every citation rendered
from an installed bundle. **Effort:** XL. **Risks/deps:** trust-model design is the hard
part (who may sign; how revocation works); safety copy in third-party bundles is a new
review problem — minimum: installed bundles cannot alter Sprout's own routing/deny-list
strings (those stay in the app, FIX-09), and toxicity-topic content from unreviewed
publishers renders with an explicit provenance banner. **Excellence bar:** an unsigned
or tampered bundle is unloadable by construction; a signed demo bundle from a second
"publisher" round-trips with citations attributing the publisher.

### EXP-16 — Extract the grounding runtime as a portfolio library (`groundedkit`)

**Pitch.** Lift the pipeline's invariant layer — citation guard, deny-list guard
framework, provenance-tagged `AnswerSentence`, fail-closed provider seam, abstention —
into a reusable library the portfolio's other grounded systems consume.

**Impact.** The Family Greenhouse integration plan (CLAUDE.md) already specifies a
second provenance class (`from your Greenhouse`); an unpublished eval harness measures other systems
against exactly these properties. One hardened implementation of "no claim without a
citation" beats N copies drifting apart — the same reasoning as the STANDARDS repo, but
for code. Sprout stays the reference deployment and test bed.

**Shape.** (a) Carve the corpus-independent core out of `guards.py`, `models.py`
(Citation/AnswerSentence/provenance), `confidence.py`, `providers/base.py` behind a
stable API; (b) Sprout consumes it as a dependency with zero behavior change (the
conformance bar: byte-identical eval report before/after); (c) a second consumer proves
the seam (Family Greenhouse Phase A is the natural candidate, per its own phasing).
**Effort:** XL. **Risks/deps:** premature extraction is the classic failure — gate on a
*real* second consumer existing, not on aspiration; CODEOWNERS/ADR guardrails must
travel with the code. **Excellence bar:** Sprout's eval byte-identical across the
extraction; the second consumer passes a provenance eval suite using the shared kit.

### EXP-17 — Close the loop: a local review console for flagged answers

**Pitch.** `Answer.low_confidence` currently flags answers "for human review" — but no
review surface exists. Build a local console that queues flagged/refused traces for
maintainer labeling, and feeds those labels into the judge probe set and the confidence
re-fit.

**Impact.** Three assets that currently starve for labels — `eval/judge_probes.yaml`
(30-day freshness gate in the ledger), FIX-08's calibration fit, and new eval cases —
all improve from the same stream of human judgments the runtime already identifies as
valuable and then drops on the floor. This is the maintainer-side complement to E5's
SME contribution path.

**Shape.** (a) An opt-in local trace sink (explicitly *not* the PII-free operational
log — a separate, user-consented capture file, off by default, documented in §C with
its own inventory row); (b) `sprout review` TUI: show trace (`Assistant.trace` already
exists), label {correct / incomplete / wrong-plant / should-have-refused}; (c)
exporters: labels → judge probes (with `human_label`), → confidence-fit dataset, →
draft eval-case YAML for curation. **Effort:** M–L. **Risks/deps:** the capture file
stores question text → DPIA delta *before* shipping, local-only, off-by-default,
documented retention; label quality is one person's judgment — mark probe provenance
accordingly (the κ gate still compares judge to *human*, now with more n).
**Excellence bar:** probe set refreshes from real reviewed traffic each release instead
of hand-authored probes; calibration and κ trends improve measurably (EXP-13 shows it).
