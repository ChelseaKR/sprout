# Research Roadmap — persona-driven, evidence-backed backlog

> **What this is.** A triaged backlog distilled from the synthetic persona panel in
> [`USER-RESEARCH.md`](USER-RESEARCH.md), cross-referenced against published
> evidence (access date **2026-06-30**). It **complements** — does not replace —
> [`docs/ROADMAP.md`](ROADMAP.md), which carries Sprout's phased build plan, metrics
> ledger, and conformance declarations. Where this file echoes a ROADMAP phase or an
> ADR, the item is tagged **[corroborates …]** (independent triangulation). Where it
> surfaces something the existing docs don't cover, it is tagged **[NET-NEW]**.
>
> **Status context.** Sprout is `In build` (Phase 3). The *engine* (pipeline, five
> eval suites, guards, fail-closed loader, providers) exists. The synthetic corpus,
> 120+ cases, baseline scoreboard, model card, ACR, red-team report, and deployed UI
> are now committed; remaining gaps are tracked in [`docs/ROADMAP.md`](ROADMAP.md).
> Several items below are retained as the research record that drove that work.
>
> **Synthetic-data caveat.** Personas are synthetic; this backlog is a hypothesis set
> to validate, not validated demand. See the warning in [`USER-RESEARCH.md`](USER-RESEARCH.md).

---

## Research basis / evidence (real sources, access date 2026-06-30)

| # | Evidence | Source(s) | Drives |
|---|---|---|---|
| EV1 | AI plant answers hallucinate, fail to cite, and amplify SEO-popularity-ranked myths; AI-generated foraging guides exist and misID is framed "life or death" | [Buncombe MG](https://www.buncombemastergardener.org/ai-and-gardening-proceed-with-caution/) · [UF/IFAS](https://gardeningsolutions.ifas.ufl.edu/design/gardening-meets-ai/) · [AI slop (Wikipedia)](https://en.wikipedia.org/wiki/AI_slop) · [OpenTools](https://opentools.ai/news/ais-green-thumb-turned-sour-how-artificial-intelligence-is-disrupting-houseplant-communities) | R1, R3, E5 |
| EV2 | Lilies → acute kidney injury in cats; *all parts* toxic; "often fatal if treatment delayed >18h"; call APCC **immediately** | [ASPCA — Which Lilies](https://www.aspca.org/news/which-lilies-are-toxic-pets) · [ASPCA Poison Control](https://www.aspca.org/pet-care/aspca-poison-control) | R7, E2, E9 |
| EV3 | "Non-toxic" ≠ safe: *any* plant material may cause vomiting/GI upset; individual pets vary | [ASPCA — Toxic & Non-Toxic Plants](https://www.aspca.org/pet-care/aspca-poison-control/toxic-and-non-toxic-plants) | R7, E1 |
| EV4 | Independent corroboration of houseplant toxicity + hotlines (Pet Poison Helpline 855-764-7661) + extension SME source | [Pet Poison Helpline](https://www.petpoisonhelpline.com/) · [NIH PMC10220692](https://pmc.ncbi.nlm.nih.gov/articles/PMC10220692/) · [UF/IFAS Hort-14 PDF](https://sfyl.ifas.ufl.edu/media/sfylifasufledu/st-johns/horticulture/pdf/Hort-14--Houseplants,-Pets,-and-Poison.pdf) | R7, E5, E9 |
| EV5 | Decontamination is time-critical; early professional consult improves outcome | [Vet Clinics: Small Animal Practice](https://www.vetsmall.theclinics.com/article/S0195-5616(13)00062-4/fulltext) | E2, E9 |
| EV6 | RAG faithfulness/groundedness + citation precision/recall are an active, contested benchmark area (Ragas/DeepEval/TruLens/attribution) | [Atlan](https://atlan.com/know/llm-evaluation-frameworks-compared/) · [DeepEval RAG triad](https://deepeval.com/guides/guides-rag-triad) · [arXiv 2505.04847](https://arxiv.org/html/2505.04847v2) · [RAGBench 2407.11005](https://arxiv.org/pdf/2407.11005) | E3, E7 |
| EV7 | Under an abstention policy, LLM-judge groundedness *saturates near 1.0*; frameworks disagree → measure, don't assume | [Abstention-policy benchmark](https://www.researchgate.net/publication/399331938_Benchmarking_Hallucination_Evaluation_for_RAG_Under_an_Abstention_Policy_A_Controlled_30-Query_Study_with_RAGAS_DeepEval_and_LLM-as-Judge) | E3, E4 |
| EV8 | Calibration (ECE) + selective prediction / coverage-risk are the formal tools for "knowing what you don't know" | [NeurIPS 2025 selective prediction](https://neurips.cc/virtual/2025/133203) · [Knowledge-Boundary survey 2412.12472](https://arxiv.org/pdf/2412.12472) | E4 |
| EV9 | Free photo-ID apps vary widely (PlantNet ~86.5% vs iNaturalist ~65.6% Top-1; genus ≫ species; varies by family; confident IDs reliable but infrequent) | [Hart et al. 2023](https://eprints.glos.ac.uk/12421/) · [Rzanny et al. 2024, *People and Nature*](https://besjournals.onlinelibrary.wiley.com/doi/full/10.1002/pan3.10676) · [iNaturalist data-quality, PMC10703310](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10703310/) | R6, R8, E8 |
| EV10 | LEP / Spanish-first information disparities; MT can be unsafe (a health dept MT said a vaccine was "not necessary"); low-resource MT lags | [JAMIA Open](https://academic.oup.com/jamiaopen/article/9/1/ooag007/8460310) · [PMC8568518](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8568518/) · [PMC6238892](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6238892/) · [PMC9205365](https://pmc.ncbi.nlm.nih.gov/articles/PMC9205365/) | R4, E6 |

---

## Remediation backlog (close gaps in what exists or is specced)

Priority: **P0** now · **P1** next · **P2** soon. Effort: **S** ≈ an afternoon · **M** ≈ a day or two · **L** ≈ a week+.

| ID | Remediation | Personas | Pri | Effort | Evidence / tag |
|---|---|---|---|---|---|
| R1 | **Author & commit the synthetic CC0 corpus + dated manifest**, prioritizing (a) the top beginner houseplants and (b) the highest-call-volume *toxic* plants (lilies, sago palm, pothos, philodendron, azalea, tulip) so the safety suite has real toxicity refs to cite | A1,A2,A4,B1,B2 | P0 | L | EV1,EV2,EV4 · **[corroborates ROADMAP Phase 1]** |
| R2 | **Author the 120+ YAML cases + commit the baseline scoreboard** (mediocre numbers shown, not hidden); wire the CI smoke suite of corpus-derived questions | C1,C2,E1 | P0 | L | EV6 · **[corroborates ROADMAP Phase 2]** |
| R3 | **Commit the model card + data card** stating limits plainly: corpus coverage gaps, extractive-but-context-incomplete risk, and "non-toxic ≠ safe" | E1,B1,C2 | P0 | M | EV1,EV3 · **[corroborates ROADMAP Phase 3]** |
| R4 | **Deploy the accessible UI behind a real URL** with the reference-implementation banner **and commit the ACR** (VPAT 2.5 Rev 508) | D1,A4,A5(→D1) | P1 | M | EV10 · **[corroborates ROADMAP Phase 3] · [DONE]** |
| R5 | **Commit the judge-calibration probe set + κ** and the **OWASP-LLM red-team report** | C1,C2 | P1 | M | EV6,EV7 · **[corroborates ROADMAP Phase 2/3]** |
| R6 | **Reconcile the photo-ID status drift**: remove/replace the "Not a plant-ID-from-photo tool" non-goal in [`RESPONSIBLE-TECH-AUDITS.md`](RESPONSIBLE-TECH-AUDITS.md) §A, and add a **photo-ID + reminders privacy/DPIA row** (Pl@ntNet egress, image-not-retained, `var/reminders.json` local state) to §C | E1,A3 | P1 | S | EV9 · **[NET-NEW]** (doc-consistency gap; complements [ADR-0010](adr/0010-photo-plant-id-as-selector-not-fact-source.md)/[ADR-0011](adr/0011-local-first-reminder-scheduler.md)) |
| R7 | **Add an explicit "non-toxic ≠ safe" disclosure** for low-toxicity plants (mild-GI-upset cases) so the never-assert-safe rule covers the *subtle* case, EN+ES; add the phrase to the safety deny-list review | A2,B1,B2 | P1 | S | EV2,EV3 · **[NET-NEW]** |
| R8 | **Surface photo-ID uncertainty in the UI**: show the visual-match label + the abstain-on-low-confidence path, screen-reader-announced; emit a "species not in corpus → fallback" message | A3,D1 | P1 | S | EV9 · **[corroborates ADR-0010]** (extend) |
| R9 | **Clarify the reminder boundary in-product**: household reminders belong in Family Greenhouse; retain the local CLI/API contract without promoting it in Sprout's public web surface | E1,D1 | P2 | S | — · **[corroborates ADR-0011; resolved by ADR-0015]** |
| R10 | **Make the eval job a required CI status check** with per-item "why it failed" traces surfaced in the report | C1,E1 | P2 | S | EV6 · **[corroborates ROADMAP Phase 2]** |

## Expansion backlog (new capability)

| ID | Expansion | Personas | Pri | Effort | Evidence / tag |
|---|---|---|---|---|---|
| E1 | **Toxicity-coverage eval slice + report panel**: assert the corpus cites a toxicity reference for every ASPCA top-N pet-toxic plant, and that "is X safe for my cat" *always* routes and *never* certifies | B1,A2,C1 | P1 | M | EV2,EV3 · **[NET-NEW]** · **[DONE]** |
| E2 | **Urgency-forward routing for ingestion** ("my cat ate a lily petal" → call-now framing + the >18h fatality window, *without* giving veterinary advice), localized EN/ES | B1,A2 | P1 | S | EV2,EV5 · **[NET-NEW]** |
| E9 | **Standardized vet/poison-control escalation card** on every toxicity answer/refusal: ASPCA APCC (888-426-4435) + Pet Poison Helpline (855-764-7661) + "what to tell them: plant, amount, time", accessible + localized | B1,A2,D1 | P1 | S | EV4,EV5 · **[NET-NEW]** |
| E3 | **External-suite comparison/ablation**: benchmark Sprout's grounding-by-construction + deterministic safety against ≥1 of Ragas/DeepEval/ALCE-style citation precision/recall; publish the (saturation-aware) result | C2 | P2 | L | EV6,EV7 · **[NET-NEW]** |
| E4 | **Coverage-vs-risk (selective-prediction) curve** in the calibration report, beyond ECE: publish the coverage/risk tradeoff at the abstain threshold | C2,C1 | P2 | M | EV8 · **[NET-NEW]** |
| E5 | **SME corpus-contribution workflow**: a low-/no-code "propose a cited passage + an eval case" path with provenance fields (source, license, fetch_date, lang, topic) enforced and a representational-harm checklist | B2,E1 | P2 | L | EV1,EV4 · **[NET-NEW]** |
| E6 | **Language expansion beyond EN/ES** (the i18n seam is one module) — *gated* on parity: each new language must clear the multilingual suite, and ES/new-language copy is human-reviewed, never raw MT | A4,B2 | P2 | L | EV10 · partially **[corroborates I18N standard]** / **[NET-NEW]** for >2 langs |
| E7 | **Citation freshness / link-liveness check**: flag when a cited source's `fetch_date` is stale or the URL no longer supports the claim — especially toxicity refs that get revised | C1,B1,E1 | P2 | M | EV6 · **[NET-NEW]** · **[shipped: `sprout freshness`]** |
| E8 | **Photo-ID "show your work"**: top-N candidate species with scores + an explicit corpus-coverage gate; never auto-act on the match | A3,A1 | P2 | M | EV9 · **[corroborates ADR-0010]** (extend) |
| E10 | **Family Greenhouse personalization (A→B→C)**: toxicity cross-check against the user's *actual* pets/plants ("a plant in your Greenhouse is listed toxic to cats, and your profile notes a cat") — deferred, opt-in, household-data ASVS L2 | A1,A2,E1 | Later | L | EV2 · **[corroborates ROADMAP deferred]** |
| E11 | **`corpus.yaml` generalization + "adapt this to your domain" guide** so any cited care corpus can be swapped in | E1,C2 | Later | M | — · **[corroborates ROADMAP Phase 4]** |

---

## Sequenced roadmap

**Now (P0 — the content unlock; nothing the user touches is real until this lands).**
R1 (toxicity-prioritized corpus + manifest), R2 (120+ cases + baseline), R3 (model/data
cards). These three convert "engine exists" into "a person can ask a real plant a real
question and the gate means something." R1 is the bottleneck for A1, A2, A4, B1, *and*
C1 at once.

**Next (P1 — make safety loud and prove the claims).** R7 + E9 + E2 (non-toxic≠safe
disclosure, escalation card, urgency-forward routing) harden the keystone control with
framing the research demands; R4 + R5 (deployed UI + ACR, judge-κ + red-team) turn three
self-claims into artifacts; R6 + R8 reconcile the photo-ID docs and surface its
uncertainty; E1 adds the toxicity-coverage slice.

**Soon (P2 — depth and credibility).** E3 + E4 (external comparison + coverage-risk
curve) earn C2's trust; E5 (SME authoring) and E7 (citation freshness) attack the corpus
bottleneck and keep safety current; E6 (gated language expansion); R9, R10 finish the
honest-limits and CI polish.

**Later (deferred, already in ROADMAP).** E10 (Family Greenhouse personalization, ASVS
L2), E11 (`corpus.yaml` generalization).

## Recommended first sprint (highest-leverage, mostly "finish what's specced")

1. **R1 — commit the toxicity-prioritized synthetic corpus + dated manifest.** The
   single unblock for half the panel (A1, A2, A4, B1) and the prerequisite for a
   meaningful eval. Lead with the highest-call-volume toxic plants (EV2/EV4).
2. **R2 — author the 120+ cases + commit the baseline scoreboard.** Mediocre numbers
   shown, not hidden. Makes the green gate mean something for C1/E1.
3. **R7 + E9 — "non-toxic ≠ safe" disclosure + standardized escalation card.** Cheap
   (S), highest *safety* leverage, directly research-backed (EV2/EV3/EV4/EV5); the
   never-certify-safe rule made *loud*, which B1 demands.
4. **R6 — reconcile the photo-ID non-goal + add the DPIA row.** The panel's clearest
   NET-NEW catch: the docs contradict the shipped feature. Cheap (S); pure honesty.
5. **R3 — commit the model + data cards.** States the limits (coverage, context-
   incompleteness, non-toxic≠safe) plainly, which every safety and research persona wants.

Bundle the afternoon-sized wins alongside: **R8** (photo-ID uncertainty surfacing),
**E2** (urgency routing copy), **R10** (eval as required check).

## Traceability matrix (persona → findings)

| Persona | Remediations | Expansions |
|---|---|---|
| A1 New plant parent | R1, R3 | E8, E10 |
| A2 Pet-toxicity owner | R1, R7 | E1, E2, E9, E10 |
| A3 Photo-ID user | R6, R8 | E8 |
| A4 Spanish-first | R1, R4 | E6 |
| B1 Vet / poison-control | R1, R3, R7 | E1, E2, E9, E7 |
| B2 Extension SME | R1, R7 | E5, E6 |
| C1 Eval / QA engineer | R2, R5, R10 | E1, E4, E7 |
| C2 RAG-eval researcher | R2, R3, R5 | E3, E4, E11 |
| D1 A11y / SR user | R4, R8, R9 | E9 |
| E1 Owner / maintainer | R3, R6, R9, R10 | E5, E7, E10, E11 |

## Validate with real users / risks

- **Safety path requires expert sign-off, not synthetic consensus.** R7/E2/E9 touch
  emergency guidance; before shipping copy that frames urgency or the >18h window,
  get a **licensed veterinary toxicologist / poison-control clinician** to review it.
  The synthetic B1 is a stand-in, not an authority. Risk if skipped: false reassurance
  or, conversely, implying triage Sprout can't do.
- **Spanish parity needs a native horticulture reviewer.** Per EV10, MT can be unsafe
  on exactly this content. Don't expand languages (E6) on automated parity scores alone;
  human-review the toxicity and routing strings.
- **Coverage vs. abstention is a UX risk, not just a metric.** EV7 shows abstaining
  systems flatter their own groundedness scores; A1 will *walk* if the corpus is so thin
  that everything refuses. Validate the answer/refuse ratio with real beginners (R1 sizing).
- **Photo-ID confident-wrong is the residual harm** even with selector-not-fact (EV9):
  test whether real users notice the "visual match, not a cited fact" label or anchor on
  the species name anyway.
- **No demand signal.** This panel cannot tell you how many real users exist or what a
  vet would require to trust the routing. Run ≥1 real interview per group before treating
  any P1+ item as committed.

## Honest limits

This roadmap is derived from a *synthetic* panel. It is a structured way to find gaps and
sequence known work — not evidence of demand, willingness to pay, or clinical adequacy. It
over-weights the maintainer's mental model and the published literature, and under-weights
whatever real users would surprise us with. Most P0 items are "finish what
[`docs/ROADMAP.md`](ROADMAP.md) already commits to," reframed by who is harmed when it's
missing; the genuinely NET-NEW contributions are the **safety-framing items (R7, E1, E2,
E9)**, the **photo-ID doc reconciliation (R6)**, the **external-suite comparison (E3/E4)**,
and the **SME authoring + citation-freshness loop (E5/E7)** — all cheap-to-moderate, all
research-backed, none requiring a new architecture. Treat the rest as hypotheses for the
real interviews this exercise exists to design.
</content>

---
## Implementation status — 2026-06-30 (working tree, uncommitted)
Shipped this pass: **R6** doc-drift fix (photo-ID non-goal reconciled with ADR-0010) · **R3** model + data cards · conservative safety framing (**R7/E9** "non-toxic ≠ safe" + escalation to ASPCA/Pet-Poison-Helpline; never asserts safe). Verify: `make verify` green. Deferred: R1 toxicity corpus + R2 eval cases (need a veterinary-toxicologist / SME).

## Implementation status — 2026-07-03
Shipped: **E7** citation freshness / link-liveness check — `sprout.freshness.check_freshness()`
parses each manifest entry's `fetch_date` and flags stale citations (365d default, 180d for
toxicity-topic entries or titles/topics that mention toxicity), plus an opt-in, network-gated
`check_liveness()` that HEAD/GETs cited URLs (skipping the synthetic `example.invalid` host)
only when explicitly requested. Wired up as `sprout freshness [--check-links]`
(`src/sprout/cli.py`), config-over-code thresholds under `corpus.freshness`
(`src/sprout/config.py`), unit-tested offline in `tests/test_freshness.py`. Verify:
`pytest tests/test_freshness.py -q`, `ruff check`, `mypy` all green; `sprout freshness`
exits 0 against the bundled 2026-05-01 corpus.

**R9 superseded and resolved by ADR-0015 (2026-07-16).** The earlier implementation put a
local-only reminders panel in `web/dist/index.html` and documented its no-sync/no-push limits.
The product-boundary review found that even an honestly limited panel duplicated Family
Greenhouse's task domain. The public Sprout surface now carries no reminder UI or household
state; the tested local CLI/API contract remains available for compatibility. Verify with
`uv run sprout a11y-check web/dist/index.html` and
`uv run pytest tests/test_server.py::test_shipped_ui_is_a_stateless_reference_surface -q`.

Shipped: **E1** toxicity-coverage eval slice (`src/sprout/eval/suites/toxicity_coverage.py`) — a deterministic, corpus-level suite asserting every ASPCA top-N pet-toxic plant in the corpus (aloe, dracaena, english-ivy, fiddle-leaf-fig, jade-plant, monstera, peace-lily, philodendron, pothos, rubber-plant, snake-plant, zz-plant) has an English document with a `## Toxicity` section that mentions toxicity and routes to a vet and a poison-control line; auto-registers a `toxicity-coverage` report panel via the existing `report.py` suite-iteration. Complements the pre-existing `safety` suite, which already gates the *live answer* on never certifying "safe" and always routing. Verify: `make verify` green (lint, type, test with 95% coverage, eval, a11y all pass); `docs/audits/eval-report.md` shows `toxicity-coverage` — ✅ PASS, n=12.
