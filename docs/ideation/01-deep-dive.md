# Deep dive — current state as read on 2026-07-01

This is an assessment from reading the repository itself (source, tests, CI, committed
artifacts), not from its self-description. Where the two disagree, that disagreement is
recorded here and becomes a fix in [`02-large-scale-fixes.md`](02-large-scale-fixes.md).

## What Sprout actually is

A retrieval-augmented houseplant-care assistant whose **eval harness is the product**.
The pipeline is deliberately narrow: `src/sprout/answer.py` (`Assistant.answer`) encodes
language resolution (`lang.py`) → safety-query classification (`guards.is_safety_query`)
→ mandatory hybrid retrieval (`retrieve.py`: cosine over `HashingEmbedding` + pure-Python
BM25 in `lexical.py`, fused by RRF, species-filtered, Jaccard-deduped) → extractive
generation (`providers/deterministic.py::ExtractiveGenerator`) → the citation guard and
never-certify-safe filter (`guards.py`) → calibrated abstention (`confidence.py`) →
answer-or-refuse. Every rendered sentence is copied verbatim from a retrieved chunk and
re-verified; toxicity questions attach a routing notice on both answer and refusal paths.

Surfaces: a Typer CLI (`src/sprout/cli.py`), a FastAPI JSON/SSE server plus
framework-free chat UI (`src/sprout/server.py`, `web/dist/`), photo plant-ID as a
*selector* (`src/sprout/identify.py`, `providers/plantnet.py`, ADR-0010), and local-first
reminders (`src/sprout/reminders.py`, ADR-0011).

The harness (`src/sprout/eval/`) is genuinely fail-closed: content-addressed datasets
with a committed sidecar hash (`dataset.py`, `eval/suites.sha256`), a wall-clock-free run
fingerprint (`runner.py`), PASS/FAIL-only verdicts with Wilson CIs (`suite.py`), a
deterministic and an Anthropic judge behind one Protocol (`judge.py`, `llm_judge.py`),
and reports in MD/HTML/JSON/JUnit/SARIF (`report.py`) with the HTML self-checked by
`a11y.py` before write.

**Status correction to the record:** `docs/ROADMAP.md` (dated 2026-06-22) lists the
corpus and eval cases as outstanding, but the working tree now contains a 16-species ×
EN/ES synthetic CC0 corpus (`corpus/processed/`, 32 files, generated via
`scripts/_materialize_content.py`), five authored suite files totaling ~150 cases
(`eval/suites/*.yaml`), and a committed eval report with real numbers *and real published
failures* (`docs/audits/eval-report.md`: safety 0.964 with `safety-025` failing on
routing, refusal 0.912, multilingual 0.917 at n=12). The RESEARCH-ROADMAP status footer
(2026-06-30) still says R1/R2 are deferred pending an SME — which is true only for the
*real* toxicity corpus (high-call-volume species like true lilies, sago palm, azalea are
absent by design); the synthetic scaffold exists and works.

## What is genuinely strong

- **The grounding contract is real code, not aspiration.** `guards.citation_guard`
  independently re-verifies every candidate against its claimed chunk, with a
  negation-polarity gate in `_supported_by` that closes the "X is not toxic" inversion
  hole; `guards.asserts_safety` is accent/hyphen-folded, bilingual, and distinguishes
  source-attributed reporting from bare certification via `_SOURCE_MARKERS`. This is a
  more careful deny-list than most production systems ship.
- **Fail-closed discipline is consistent.** Missing sidecar → refuse to load
  (`dataset.load_suite_dir`); zero-item suite cannot PASS (`suite.SuiteResult`
  validator); cloud providers return `[]` on any error (`providers/bedrock.py`), which
  the pipeline renders as a refusal.
- **Failures are published.** The committed report shows failing calibration bins,
  the failing safety case, and an explicitly under-powered multilingual CI. That is rare
  and load-bearing for credibility.
- **The safety copy shipped on 2026-06-30 is well-constructed**: urgency-forward routing
  (`PromptConfig.safety_route_by_lang`), the "non-toxic ≠ safe" caveat
  (`nontoxic_caveat_by_lang`), and the escalation card (`escalation_card_by_lang`) in
  `src/sprout/config.py` — all EN/ES, all downstream of the deny-list so they survive it.
- **Reproducibility is engineered**: `determinism.py`, sorted-key JSON everywhere, the
  fingerprint excluding wall-clock, `record.py` replaying the live engine into goldens.

## Structural debt and gaps actually observed

1. **Numeric doc drift.** `config/sprout.yaml` sets `abstain_threshold: 0.25` /
   `low_confidence_threshold: 0.50`, and the committed eval report agrees ("abstention
   enforced below the 0.25 confidence threshold") — but `docs/cards/model-card.md`
   ("default **0.45**" / "**0.62**"), `docs/RESPONSIBLE-TECH-AUDITS.md` §D, the red-team
   report's config line, and the ROADMAP ledger's abstention row all still say 0.45/0.62.
   Similarly the ROADMAP ledger declares refusal ≥ 0.95 while the shipped suite gate is
   0.90 (honestly explained inside the report, never reconciled in the ledger), and
   `CLAUDE.md` says "WCAG 2.2 AAA" in three places while every other artifact says AA.
2. **Claimed AUTO gates that no CI line enforces.** No latency test exists anywhere in
   `tests/` despite the ledger's "p95 < 200 ms — AUTO" row; `report.diff_against_baseline`
   is implemented and unit-tested but never called by `cli.py` or CI, so the
   "no regression past tolerance from baseline" gate is unwired; `sprout calibrate` runs
   in CI without `--gate` (exit 0 always); the Wilson statistical gate defaults off and
   CI does not pass `--statistical-gate`; `ci.yml`'s pa11y job is
   `continue-on-error: true` + `|| true` while RESPONSIBLE-TECH-AUDITS §E claims
   "pa11y-ci **blocking**"; CodeQL is claimed in §F and the ROADMAP but no workflow
   exists; `release.yml`'s SBOM step ends in `|| true`, which STANDARDS/README.md
   explicitly forbids for AUTO gates.
3. **Safety classification coverage is keyword-thin at the edges.** The committed report
   itself shows `safety-025` failing "no vet/poison routing." `is_safety_query` keys on
   cat/dog/pet/child lists in `GuardsConfig.toxicity_keywords`; other companion animals
   (rabbit, bird, hamster, reptile) are absent, and a refusal path can only get routing
   from input keywords (the topic-based `toxicity_cited` OR in `answer._render` applies
   to rendered answers only).
4. **The escalation card is animal-only while the classifier includes children.**
   `toxicity_keywords` includes child/children/baby/toddler and the routing copy says
   "pet or child," but `escalation_card_by_lang` names only ASPCA APCC and Pet Poison
   Helpline — animal lines. A "my toddler chewed a pothos leaf" question receives a card
   pointing at animal poison control. (Fixing the copy is SME-gated; see FIX-13.)
5. **Unknown-species toxicity questions can ground in the wrong plant.** With no species
   filter hit, `Retriever._candidates` falls back to the whole corpus, and
   `has_grounding` needs only min_score + one shared content token ("toxic", "cats"), so
   an off-corpus species question can render cited sentences about a different plant.
   The report's refusal notes acknowledge the general class; the *toxicity-specific*
   severity of it is unaddressed.
6. **Dual-copy data with no parity gate.** `corpus/` + `config/sprout.yaml` are
   duplicated under `src/sprout/data/` for packaging (`resources.py`). The copies are
   byte-identical today, but `scripts/_materialize_content.py` writes only the top-level
   copy, so the next regeneration desynchronizes the packaged corpus silently;
   `tests/test_resources.py` checks existence, not equality.
7. **Per-query index construction.** `Retriever.retrieve` builds a fresh `BM25Index` on
   every call and `VectorStore.search` is a full O(N·dim) Python scan invoked with
   `top_k=len(store)`. Harmless at ~370 chunks; incompatible with the corpus scale the
   safety mission requires (ASPCA-scale coverage) and with the declared 200 ms budget.
8. **Dead or unimplemented config.** `ServerConfig.session_memory` (config.py:407) is
   documented in RESPONSIBLE-TECH-AUDITS §C as an in-memory session window, but
   `server.py` holds no session state at all. `hypothesis` is a declared dev dependency
   with zero uses in `tests/`.
9. **Language data is scattered.** EN/ES lives in at least six places with different
   shapes: `PromptConfig`/`GuardsConfig` dicts, `guards._HARM_TOKENS`/`_SOURCE_MARKERS`
   (mixed-language frozensets), `lang.py` marker sets, and bilingual term lists inside
   `eval/suites/safety.py`. E6 (language expansion) is structurally expensive until this
   is consolidated.
10. **Branch state.** `main` is two commits behind: photo-ID/reminders (`7ce4e83`) and
    the research pass + safety copy (`b05f870`) live on side branches. Everything above
    describes the branch head, not what a visitor to `main` sees.

## Strategic position in the portfolio

Sprout is the portfolio's cleanest demonstration of *grounding-by-construction plus
eval-as-product* — the safe-domain sibling of an unpublished eval harness and the designated client of
`family-greenhouse`'s API (integration fully specced in `CLAUDE.md`, deliberately
deferred). Its differentiators are exactly the ones the fixes below protect: published
failures, deterministic reproducibility, and the conservative safety posture. Its
biggest strategic liability is also portfolio-wide: the paperwork occasionally claims a
half-step more than the wiring delivers, and in a repo whose thesis is "honesty as a
feature," the *claims ledger itself* has to be held to the same gate discipline as the
code. That is the organizing idea behind FIX-01/FIX-02.

Uncertainties worth naming: I did not run the suites (per task constraints), so all
numbers quoted are from committed artifacts; branch-protection settings (required
`ci-gate`) are not verifiable locally; and the ZWSP/homoglyph deny-list bypass in FIX-05
is hypothesized from reading `guards._fold` and `text.py` call sites, not demonstrated.
