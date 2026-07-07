# Large-scale fixes — FIX-01 … FIX-13 (drafted 2026-07-01)

Deep structural fixes grounded in the observations of
[`01-deep-dive.md`](01-deep-dive.md). None restates an R-item from
[`../RESEARCH-ROADMAP.md`](../RESEARCH-ROADMAP.md); where a fix touches the same terrain
as an existing item, the delta is stated. Effort tiers: **S** ≈ a day, **M** ≈ a few
days, **L** ≈ 1–2 weeks, **XL** ≈ multi-week.

---

## FIX-01 — Claims-integrity gate: no number in the docs without a machine-checked source

**Pitch.** Make every numeric self-claim in the documentation provably equal to the
value the code enforces — the honesty ethos applied to Sprout's own paperwork.

**Why it matters.** Four independent drift instances exist right now: abstention
thresholds (0.45/0.62 in `docs/cards/model-card.md`, `docs/RESPONSIBLE-TECH-AUDITS.md`
§D, `docs/audits/red-team-2026-06-22.md` vs 0.25/0.50 in `config/sprout.yaml` and the
committed eval report); the refusal target (ROADMAP ledger ≥ 0.95 vs shipped suite gate
0.90 in `src/sprout/eval/suites/refusal.py` — the report explains it, the ledger never
adopted it); AA vs AAA (`CLAUDE.md` ×3 vs everything else); the data-card species table
listing plants not in the corpus (Dieffenbachia, Areca palm, African violet, Hoya). Each
one hands a skeptical reviewer (persona C2, D1) a reason to distrust the claims that
*are* true.

**Shape of the work.** (a) A `docs/claims.yaml` registry mapping each numeric claim to
its source of truth (`config/sprout.yaml` key, suite `MetricDefinition.threshold`, or
`docs/audits/eval-report.json` field); (b) a `sprout claims-check` command (sibling of
`a11y-check` in `cli.py`) that greps registered claim sites and fails on mismatch;
(c) wire into `Makefile verify` and `ci.yml`; (d) one-time reconciliation pass fixing
the four known drifts (decide 0.25/0.50 and AA as canonical — they match shipped
behavior — and update the model card, audits doc, ledger row, and CLAUDE.md).

**Effort:** M. **Risks/deps:** regex-based claim extraction is brittle — mitigate with
explicit `<!-- claim:… -->` markers at claim sites; red-team report is a dated artifact
and should get an erratum note, not a rewrite. **Excellent looks like:** `make verify`
fails if any registered claim drifts; zero unregistered numeric thresholds in
`docs/**/*.md` (checked by an allowlist audit); the 2026-07 reconciliation commit is the
last manual one ever needed.

## FIX-02 — Enforcement parity: every "AUTO" row maps to a CI line, or gets relabeled

**Pitch.** Close the gap between declared gates and wired gates across seven observed
instances — make the ledger's AUTO column mechanically true.

**Why it matters.** The ROADMAP ledger and RESPONSIBLE-TECH-AUDITS declare AUTO gates
that nothing enforces: latency budget (no test exists), baseline no-regression
(`report.diff_against_baseline` implemented + tested, never called from `cli.py` or CI),
judge-calibration gating (`ci.yml` runs `sprout calibrate` without `--gate`, so it can
never fail), the Wilson statistical gate (off by default, not passed in CI), blocking
pa11y (job is `continue-on-error: true` while §E claims blocking), CodeQL (claimed in §F
and README table; no workflow file), and the release SBOM (`cyclonedx-py … || true` in
`release.yml`, which `STANDARDS/README.md` forbids for AUTO). This is the single largest
threat to the repo's core credibility claim.

**Shape of the work.** For each: wire it or demote it honestly. Concretely: add a
latency budget test (offline p95 over the demo questions, generous CI margin); teach
`sprout eval` to load `docs/audits/eval-baseline.json`, call `diff_against_baseline`,
and fold regressions into `exit_code`; add `--gate` to the CI calibrate step (keep the
deterministic judge reported-not-gated per its own docstring — gate the probe-set
freshness instead); make pa11y blocking with a curated ignore list or relabel §E;
add `codeql.yml` or strike the claim; drop `|| true` from SBOM. Add a small
"gate-inventory" doc test that asserts every ledger row's `Measured by` names an
existing make target/CI step (the mechanical spine of the fix).

**Effort:** L (each item S, but seven of them plus the inventory test).
**Risks/deps:** enabling the statistical gate flips multilingual to FAIL at n=12
(CI lower bound 0.646 < 0.85) — sequence after FIX-12; pa11y-in-CI needs a served app
and is flake-prone (pin browser, retry policy). **Excellent looks like:** a
`docs/audits/gate-inventory.md` table generated in CI mapping every AUTO row → CI step →
last status, with zero "declared but unenforced" rows.

## FIX-03 — Unknown-species hard gate for toxicity questions

**Pitch.** Never answer a toxicity question about a plant the corpus does not cover —
even when generic toxicity passages score well enough to ground.

**Why it matters.** `Retriever._candidates` (retrieve.py) falls back to the whole corpus
when `_named_species` finds nothing, and `has_grounding` requires only `min_score` plus
one shared content token — for "is dieffenbachia toxic to cats?" the tokens "toxic" and
"cats" are shared with *every* toxicity chunk. The worst case is a fluent, fully-cited
answer about the wrong species on the one query class where wrongness is dangerous. The
committed report's refusal-suite notes acknowledge the general unknown-species weakness;
this fix removes it structurally for the safety-critical slice instead of hoping the
score gate catches it.

**Shape of the work.** (a) A species-mention detector: unresolved capitalized
binomials / plant-like noun phrases that match neither corpus slugs
(`Assistant.species_slugs`) nor `retrieval.species_aliases`, backed by a small
off-corpus gazetteer of common houseplant names (dieffenbachia, sago palm, azalea,
oleander, …); (b) in `answer.py`, when `is_safety_query` is true *and* the query names a
species that does not resolve, refuse with `refusal_reason="species_not_covered"` — the
existing refusal + escalation path already attaches routing; (c) new eval cases in
`eval/suites/refusal.yaml` and `safety.yaml` for named-but-uncovered species; (d) a
crisp localized message ("I don't have a cited reference for that plant") — copy change,
so it queues behind the safety-copy review gate.

**Effort:** M. **Risks/deps:** false positives (a nickname the alias map should have
had) increase refusals — mitigate by expanding `species_aliases` alongside; gazetteer
species names are not safety *advice* but ship with the SME review anyway.
**Excellent looks like:** a dedicated eval slice where 100% of named-off-corpus toxicity
questions refuse-with-routing; zero cited answers naming a different species than the
question.

## FIX-04 — Routing coverage: topic-aware refusals and species-inclusive vocabulary

**Pitch.** Attach vet/poison routing wherever the *evidence* says toxicity, not only
where input keywords do — and stop assuming every pet is a cat or dog.

**Why it matters.** The committed report shows `safety-025` failing with "no vet/poison
routing." Structurally: `answer._render` ORs in `toxicity_cited` (retrieved-chunk topic
== "toxicity") for answers, but `_refuse` keys routing solely off `is_safety_query`
keyword hits; and `GuardsConfig.toxicity_keywords` lists cat/dog/kitten/puppy but no
rabbit, bird, hamster, guinea pig, reptile (EN or ES). A "my rabbit ate monstera" phrasing
that dodges the keyword list gets a refusal with no routing.

**Shape of the work.** (a) Thread the retrieved-chunk topics into the refusal path so a
refusal after retrieving toxicity chunks still routes (plumb `retrieved` into `_refuse`
in `answer.py`); (b) extend `toxicity_keywords` EN/ES with the broader companion-animal
vocabulary (mechanical list change; existing reviewed copy is untouched); (c) regression
cases per animal per language in `eval/suites/safety.yaml`; (d) diagnose and pin
`safety-025` specifically as a named regression test.

**Effort:** S–M. **Risks/deps:** broader keywords increase safety-notice frequency on
borderline queries — acceptable by design (conservative direction is the house style);
copy itself unchanged so no new SME gate. **Excellent looks like:** safety suite at
1.000 on the routing criterion across an expanded case set, including non-cat/dog
animals in both languages.

## FIX-05 — Adversarial hardening of the guards via property-based fuzzing

**Pitch.** Use the already-declared-but-unused `hypothesis` dependency to attack
`asserts_safety`, `_supported_by`, and `citation_guard` with the inputs a cloud
generator or adversarial corpus could actually produce.

**Why it matters.** The deny-list folds accents and hyphens (`guards._fold`) but —
from reading `text.py` call sites — plausibly not zero-width characters, homoglyphs
(Cyrillic "а" in "sаfe"), or letter-spacing ("s a f e"); the coverage-based
`_supported_by` admits same-plant recombination (already honestly documented in the
model card's cloud-mode residual). These matter only on the cloud path — which is
exactly the path with no by-construction guarantee. This is hypothesized, not
demonstrated; the fix starts by demonstrating or falsifying it.

**Shape of the work.** (a) Property tests in a new `tests/test_guard_fuzzing.py`:
metamorphic invariants ("if `asserts_safety(s)` then `asserts_safety(perturb(s))`" for
unicode-confusable, ZWSP-injection, spacing, and case perturbations); (b) NFKC-normalize
and strip zero-width/format characters in `_fold` and `text.normalize` if the tests find
holes; (c) fuzz `citation_guard` with sentence recombinations across two chunks of the
same plant to quantify the documented residual and record the measured admit-rate in the
model card instead of the current qualitative note; (d) file every surviving bypass as
an eval case per the model card's own instruction.

**Effort:** M. **Risks/deps:** normalization changes touch a CODEOWNERS-guarded file
(`guards.py`) → needs an ADR per the README hard-guardrails rule; hypothesis runtime in
CI is bounded with profiles. **Excellent looks like:** a committed fuzzing report;
deny-list invariance under the perturbation classes; the recombination residual carries
a *number*.

## FIX-06 — Single-source data packaging (kill the silent dual-copy)

**Pitch.** Make the packaged corpus/config provably identical to the repo corpus/config
— or generated from it — so `pipx install sprout` can never serve different facts than
the repo shows.

**Why it matters.** `corpus/` and `config/sprout.yaml` are duplicated under
`src/sprout/data/` for the `resources.py` packaged fallback. They are byte-identical
today, but `scripts/_materialize_content.py` regenerates only the top-level copy, and
`tests/test_resources.py` asserts existence, not equality. One regeneration away from
shipping a stale corpus to installed users — a provenance failure in a repo whose rule
is "corpus is versioned and dated."

**Shape of the work.** Either (a) a hatchling build hook that copies `corpus/` +
`config/sprout.yaml` into the wheel at build time and deletes `src/sprout/data/` from
the tree, or (b) keep the vendored copy but add a parity test hashing both trees
(`sha256_of_obj` from `determinism.py` over sorted relative-path→content maps) and teach
`_materialize_content.py` to write both. Option (a) is cleaner; (b) is smaller.

**Effort:** S–M. **Risks/deps:** build-hook path must keep `uv run` dev flows working
(resources.locate falls back correctly); sdist include list in `pyproject.toml` already
carries both copies. **Excellent looks like:** it is *impossible* to commit a desynced
pair — either the second copy no longer exists, or CI fails on inequality.

## FIX-07 — Retrieval scale architecture: persistent BM25 + bounded search

**Pitch.** Move index construction to ingest time so the retrieval path stays inside
the latency budget as the corpus grows toward real safety coverage.

**Why it matters.** `Retriever.retrieve` constructs a fresh `BM25Index` over candidate
texts on **every query**, and `VectorStore.search` scans all vectors in pure Python with
`top_k=len(self._store)`. At 16 species (~370 chunks) this is fine; at the corpus scale
R1's mission implies (hundreds of species × 2+ languages), per-query indexing plus a
full scan breaks the declared 200 ms p95 (a gate FIX-02 makes real) and makes `serve`
throughput collapse.

**Shape of the work.** (a) Build BM25 postings at ingest (`ingest.py`) and persist them
in `index.json` (bump `_FORMAT_VERSION`, keep sorted-key determinism); (b) species-filter
by pre-grouped chunk-id sets instead of re-tokenizing candidates; (c) keep the pure-Python
path as the reference implementation and add an optional numpy fast path behind the same
`VectorStore` interface — determinism preserved (same floats, fixed order); (d) the
latency test from FIX-02 becomes this fix's acceptance gate, run at a synthetically
inflated corpus (e.g., 100× duplication) to test the curve, not the point.

**Effort:** M. **Risks/deps:** index format migration needs a load-error message
pointing at `sprout ingest` (pattern already exists in `store.load`); "no database
without an ADR" rule respected — this stays a flat file. **Excellent looks like:** p95
retrieval flat-ish in corpus size up to ~10k chunks; per-query allocation of BM25
structures gone; byte-identical `index.json` for identical inputs still holds.

## FIX-08 — Confidence re-fit tooling (stop hand-tuning the logistic)

**Pitch.** Replace the hard-coded logistic constants in `confidence.py` with a fitted,
provenance-stamped calibration artifact and a command that re-fits it without touching
the eval set.

**Why it matters.** `_MIDPOINT = 0.30`, `_STEEPNESS = 6.0`, `_MARGIN_BONUS = 0.05` carry
a comment "Re-fit if the corpus or retrieval changes materially" — but no tool exists,
and the committed report already shows mid-range bins failing ([0.4,0.5) and [0.5,0.6)
segments FAIL inside an overall ECE pass). Every fix/expansion that changes retrieval
(FIX-07, EXP-03) silently invalidates these constants; today nothing would notice except
a slow ECE drift.

**Shape of the work.** (a) A `sprout fit-confidence` command that replays the assistant
over a **train split** of generated calibration questions (never `eval/suites/` — the
anti-tuning-to-test discipline the ROADMAP already states), fits midpoint/steepness by
logistic regression on (best-cosine, margin) → correctness, and writes them to
`config/sprout.yaml` under a new `confidence.fit:` block with dataset hash + date;
(b) `score_confidence` reads constants from config instead of module globals;
(c) an ADR, since `confidence.py` is CODEOWNERS-guarded; (d) a drift check: eval fails
if the fit's recorded retrieval-config hash no longer matches the live one.

**Effort:** M. **Risks/deps:** needs a question generator or held-out split — the
per-species corpus structure makes leave-species-out splits natural; must keep the
transparent-function property (no learned model beyond the 3-parameter logistic).
**Excellent looks like:** all reliability bins pass, ECE ≤ 0.10, and the constants file
answers "fitted on what, when, against which config."

## FIX-09 — Consolidate language data into per-language bundles with a completeness gate

**Pitch.** One place per language, one validator, so language #3 is a data drop instead
of an eight-file surgery.

**Why it matters.** EN/ES currently lives in: `PromptConfig` (six `*_by_lang` dicts),
`GuardsConfig` (`forbidden_safe_phrases`, `toxicity_keywords`, `route_terms`),
`guards._HARM_TOKENS`/`_SOURCE_MARKERS` (mixed-language frozensets), `lang.py` marker
sets, and bilingual term lists hard-coded in `eval/suites/safety.py`
(`_VET_TERMS`/`_POISON_TERMS`). RESEARCH-ROADMAP E6 gates *adding* a language on parity;
this fix is the prerequisite refactor E6 doesn't mention — and it aligns with the
portfolio-wide i18n Phase 1 (dict → gettext) already in flight elsewhere.

**Shape of the work.** (a) A `src/sprout/locales/{en,es}/` bundle (YAML or gettext,
matching the portfolio migration) carrying prompts, deny-list, keywords, markers, and
suite vocabulary; (b) a load-time completeness validator keyed off
`languages.supported` — a missing key fails at startup, not at render (extends the
existing key-parity gate the README claims); (c) `lang.py` markers and the safety suite
consume the same bundles; (d) `_HARM_TOKENS` split per-language (folding stays).

**Effort:** L. **Risks/deps:** touches guarded files → ADR; behavior must be
character-identical for EN/ES (snapshot-test all rendered strings before/after);
E6 remains gated on human review of any *new* language's safety strings.
**Excellent looks like:** `grep -r "es\":" src/` finds no inline Spanish outside
`locales/`; adding a stub `fr/` bundle fails the completeness gate rather than silently
falling back to English.

## FIX-10 — Deploy-grade server hardening (the ASVS step-up R4 quietly requires)

**Pitch.** Before the UI goes behind a real URL, give the FastAPI surface the L2-facing
controls the offline posture deliberately skipped — as code, not as a hosting checkbox.

**Why it matters.** `server.py` states "rate-limiting/CORS/auth are left to the proxy
layer," which is correct offline but becomes the gap the moment RESEARCH-ROADMAP R4
(deploy the UI) lands: no rate limits, no CSP/security headers, `/api/identify` accepts
~8 MB base64 JSON bodies (amplified ~1.33× by encoding) with no concurrency cap, and
ADR-0008 explicitly scopes ASVS L1 to the *offline* mode. R4 ships a public, unauthenticated
inference endpoint; the audits doc already promises the posture "steps up to L2" —
nothing yet implements the step.

**Shape of the work.** (a) Committed reverse-proxy config (`infra/` Caddyfile or nginx)
with CSP, HSTS, rate limits, body-size caps; (b) app-level guards that hold even without
the proxy: request-size middleware, per-IP token bucket for `/api/identify`, bounded
worker concurrency; (c) replace `engine._store` private access in `readyz` with a public
`Assistant.index_size()`; (d) an ASVS L2 delta checklist committed under `docs/audits/`
covering only the deployed surface; (e) budget alarm wiring per the README's
cost promise.

**Effort:** M–L. **Risks/deps:** sequenced with R4 (not before it's real); keep the
offline CLI path zero-dependency — all hardening is `serve`-only. **Excellent looks
like:** the deployed URL passes an external scan (securityheaders.com A, zap baseline
clean), photo-endpoint abuse is rate-limited by test, and the L1→L2 step is a committed
artifact, not a sentence.

## FIX-11 — Retire or honestly re-document the phantom session window

**Pitch.** `session_memory` exists in config and in the DPIA but not in the code; make
the paperwork true this week, and let multi-turn arrive later as a designed feature.

**Why it matters.** `ServerConfig.session_memory` (config.py:407, default 4) is cited in
`docs/RESPONSIBLE-TECH-AUDITS.md` §C ("keeps at most a small in-memory session window")
— but `server.py` implements no session of any kind. The *reality* (fully stateless) is
privacy-better than the documented state; the drift is still a defect under the repo's
own "silent deviation" rule, and a DPIA that describes nonexistent state undermines the
data-inventory's credibility.

**Shape of the work.** Remove the field from `ServerConfig` and both YAML copies, fix
§C to say "stateless per-request; no session state of any kind," and leave a pointer to
EXP-07 (grounded multi-turn) as the designed path if session context ever returns.

**Effort:** S. **Risks/deps:** none — config is `extra="forbid"`, so removing the field
requires touching both YAML copies (interacts with FIX-06). **Excellent looks like:**
data inventory lists zero state the code doesn't have; EXP-07, if built, re-introduces
it behind its own DPIA row.

## FIX-12 — Statistical power for the multilingual and safety suites

**Pitch.** Grow the under-powered slices (multilingual n=12, safety n=28) past n≥30 so
the Wilson gate can be turned on without lying to ourselves about precision.

**Why it matters.** The committed report flags both suites under-powered; the
multilingual 95% CI is [0.646, 0.985] around a 0.917 score — the gate is effectively
decorative at this n, and one flaky ES case moves the score 8 pp. FIX-02 wants
`--statistical-gate` on in CI; flipping it today would fail multilingual on power, not
on quality. This is distinct from R2 (author the cases at all — done): it is a
power-analysis-driven sizing pass.

**Shape of the work.** (a) Author ~20 more ES mirror cases and ~10 more toxicity cases
(they exist in EN; mirror + record via `record.py`); (b) set per-suite minimum-n in the
suite registry so `underpowered` becomes a FAIL condition once targets are set;
(c) then enable the statistical gate in `Makefile`/`ci.yml` (completes FIX-02);
(d) ES case text queues behind the native-Spanish-reviewer gate the RESEARCH-ROADMAP
already names for exactly this content.

**Effort:** M (case authoring dominates). **Risks/deps:** Spanish safety strings need
the human reviewer — do EN-side sizing first; enabling min-n before authoring flips CI
red (sequence carefully). **Excellent looks like:** every suite n ≥ 30, Wilson gate on,
and the report's ⚠️ under-powered flags gone without loosening any threshold.

## FIX-13 — Split the escalation card by exposure type: humans are not routed to animal poison control

**Pitch.** A child-ingestion question currently receives a card naming ASPCA APCC and
Pet Poison Helpline — animal lines. Add a human-poison-control variant, gated on
clinician review.

**Why it matters.** `GuardsConfig.toxicity_keywords` includes child/children/baby/
toddler (EN) and niño/niña/bebé (ES), and `safety_route_by_lang` says "pet **or
child**" — but `escalation_card_by_lang` (config.py:309) names only the two animal
lines. For the highest-stakes human case the card is at best confusing, at worst a
delay. This extends the shipped E9 card (RESEARCH-ROADMAP) to the audience the
classifier already detects; E9 itself never distinguished audiences.

**Shape of the work.** (a) Detect exposure type from the same keyword pass (child-terms
vs animal-terms vs ambiguous); (b) a second card variant for human exposure (US: Poison
Control 1-800-222-1222 / webPOISONCONTROL, ES-localized), shown alongside — never
instead of — the urgent-call framing; ambiguous queries show both; (c) eval cases
asserting a child-ingestion question surfaces a human poison line; (d) **hard gate: no
copy ships without review by a poison-control clinician / medical toxicologist, in both
languages** — the numbers, the phrasing, and the decision to include them at all are
theirs to approve. The "non-toxic ≠ safe" caveat and never-certify-safe rule apply
unchanged to the human path.

**Effort:** S–M in code; the gate dominates the calendar. **Risks/deps:** SME access is
the blocker (same recruitment as RESEARCH-ROADMAP's vet-toxicologist ask — one outreach,
two review scopes); non-US numbers are out of scope until a locale story exists (note it
honestly in the card copy). **Excellent looks like:** exposure-type routing is
deterministic and eval-gated; a clinician's dated sign-off is committed under
`docs/audits/` before the copy renders anywhere.
