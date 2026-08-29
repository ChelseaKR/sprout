# User Research — Synthetic Personas & Simulated Interviews

> [!WARNING]
> **These personas and interviews are synthetic.** They were generated as a
> structured brainstorming device — *not* conducted with real people. No real
> user, veterinarian, extension agent, or auditor said any of this. The panel is a
> way to pressure-test Sprout from every angle at once; it is **not** evidence of
> demand and does **not** substitute for real discovery. Treat every "quote" as a
> hypothesis to validate, not a finding. This is consistent with how the project
> labels its bundled corpus and eval data as **synthetic and CC0** — see
> [`docs/cards/data-card-corpus.md`](cards/data-card-corpus.md).
>
> Persona needs are mapped only to **features that actually exist in the repo**
> (the four hard rules, the eval suites, photo-ID-as-selector per
> [ADR-0010](adr/0010-photo-plant-id-as-selector-not-fact-source.md), local
> reminders per [ADR-0011](adr/0011-local-first-reminder-scheduler.md), EN/ES
> parity, WCAG 2.2 AA). No feature, fact, or statistic about Sprout was invented.
> External claims carry **real citations** (access date **2026-06-30**).
>
> The honest next step is real interviews with ≥1 person per group — above all a
> licensed **veterinary toxicologist / poison-control** reviewer for the safety
> path. The triaged backlog this panel produces lives in
> [`RESEARCH-ROADMAP.md`](RESEARCH-ROADMAP.md).
> **Last assembled: 2026-06-30.**

---

## Why do this at all

Sprout is unusual: the *assistant* is a means, and the **eval harness is the
product**. That doubles the cast. There are people who *ask* a plant a question
(beginner, pet owner, photo-uploader, Spanish-first, screen-reader user); people
whose job is to *keep the answer safe* (a vet/poison-control desk, a
cooperative-extension horticulturist); people who *build and grade* the harness
(QA engineer, RAG-eval researcher); and the *operator*. Role-playing all of them
forces the question "who is each guarantee *for*?" — and surfaces the gap between
what the docs claim and what is committed today (Sprout is `In build`, Phase 3).

## Method

- **Frame.** Sample the real audiences of a grounded, evaluated, bilingual
  plant-care assistant whose headline artifact is a public eval report. Five
  groups: **Ask & Care** (the person with a plant and a worry) · **Keep Safe**
  (the toxicity/vet/SME axis the safety path routes *to*) · **Build & Evaluate**
  (who runs and extends the harness) · **Assure & Audit** (who verifies the
  accessibility and grounding claims independently) · **Operate** (the
  maintainer).
- **Protocol.** Each persona gets: a **Goal**; **Values today** — mapped to a
  *real, shipped-or-specced* Sprout feature, not a wish; **Gets stuck** — a
  friction grounded in the current `In build` status or an honest limit; **Wants
  next**; and **Adopts / walks** — the single thing that converts or kills them.
- **Synthesis.** Frictions become **R**emediations, wishes become
  **E**xpansions, deduped and triaged in
  [`RESEARCH-ROADMAP.md`](RESEARCH-ROADMAP.md). Items that echo an existing
  [`docs/ROADMAP.md`](ROADMAP.md) line or an ADR are tagged **[corroborates …]**
  (triangulation is signal); items the existing docs don't cover are **[NET-NEW]**.

### Research basis (real sources; access date 2026-06-30)

The panel is anchored to published evidence so the personas argue from reality, not vibes:

- **Online plant-care advice is low-trust and getting worse.** Cooperative-extension
  and horticulture writers document that AI answers and AI Overviews hallucinate,
  fail to cite, and *amplify SEO-popularity-ranked myths* rather than correct them
  ([NC State Extension — Buncombe Master Gardener](https://www.buncombemastergardener.org/ai-and-gardening-proceed-with-caution/);
  [UF/IFAS Gardening Solutions](https://gardeningsolutions.ifas.ufl.edu/design/gardening-meets-ai/)).
  In adjacent plant domains misidentification is framed as "literally life or
  death," with AI-generated foraging guides already on the market
  ([Wikipedia: AI slop](https://en.wikipedia.org/wiki/AI_slop);
  [OpenTools](https://opentools.ai/news/ais-green-thumb-turned-sour-how-artificial-intelligence-is-disrupting-houseplant-communities)).
  → motivates **citation-or-silence** and **groundedness-by-construction**.
- **Pet toxicity is genuinely high-stakes and time-critical.** True lilies cause
  acute kidney injury in cats; *all parts* are toxic and exposure is "often fatal
  if treatment is delayed longer than 18 hours," with the ASPCA Animal Poison
  Control Center (APCC, 888-426-4435) advising owners to call *immediately*
  ([ASPCA — Which Lilies Are Toxic to Pets](https://www.aspca.org/news/which-lilies-are-toxic-pets);
  [ASPCA Poison Control](https://www.aspca.org/pet-care/aspca-poison-control)).
  Corroborated by the [Pet Poison Helpline (855-764-7661)](https://www.petpoisonhelpline.com/),
  a peer-reviewed review of houseplant toxicity
  ([NIH PMC10220692](https://pmc.ncbi.nlm.nih.gov/articles/PMC10220692/)), and
  veterinary toxicology guidance that decontamination is most effective inside a
  short post-ingestion window
  ([Vet Clinics: Small Animal Practice](https://www.vetsmall.theclinics.com/article/S0195-5616(13)00062-4/fulltext)).
  Critically, ASPCA's own list warns that **"non-toxic" does not guarantee safe** —
  *any* plant material can cause vomiting/GI upset and individual pets vary
  ([ASPCA — Toxic and Non-Toxic Plants](https://www.aspca.org/pet-care/aspca-poison-control/toxic-and-non-toxic-plants)).
  → directly validates **never-certify-"safe" + mandatory vet/poison-control routing**.
- **Grounding, citation, and abstention are measurable — and the measurement is
  contested.** RAG faithfulness/groundedness and citation precision/recall are an
  active benchmark area (Ragas, DeepEval, TruLens, attribution suites:
  [Atlan comparison](https://atlan.com/know/llm-evaluation-frameworks-compared/);
  [DeepEval RAG triad](https://deepeval.com/guides/guides-rag-triad);
  [arXiv 2505.04847](https://arxiv.org/html/2505.04847v2);
  [RAGBench arXiv 2407.11005](https://arxiv.org/pdf/2407.11005)), and under an
  explicit abstention policy LLM-judge groundedness *saturates near 1.0* while
  frameworks disagree on hallucination
  ([abstention-policy benchmark](https://www.researchgate.net/publication/399331938_Benchmarking_Hallucination_Evaluation_for_RAG_Under_an_Abstention_Policy_A_Controlled_30-Query_Study_with_RAGAS_DeepEval_and_LLM-as-Judge)).
  Calibration (ECE) and selective prediction / coverage-risk are the formal tools
  for "knowing what you don't know"
  ([NeurIPS 2025 selective prediction](https://neurips.cc/virtual/2025/133203);
  [Knowledge-Boundary survey, arXiv 2412.12472](https://arxiv.org/pdf/2412.12472)).
  → validates **judge≠answer, deterministic safety scoring, ECE, abstention**.
- **Photo plant-ID is useful but error-prone.** Free apps vary widely — one study
  reports PlantNet ~86.5% vs iNaturalist ~65.6% Top-1, with genus-level far higher
  than species-level and accuracy varying by plant family; iNaturalist's *confident*
  IDs were reliable but it only volunteered one ~66% of the time
  ([Hart et al. 2023, U. Gloucestershire](https://eprints.glos.ac.uk/12421/);
  [Rzanny et al. 2024, *People and Nature*](https://besjournals.onlinelibrary.wiley.com/doi/full/10.1002/pan3.10676)).
  → validates **photo-ID-as-selector-not-fact** ([ADR-0010](adr/0010-photo-plant-id-as-selector-not-fact-source.md)).
- **Spanish-first access is a real equity gap.** LEP populations face documented
  health-adjacent information disparities, and machine translation can be unsafe —
  a state health department MT once told Spanish readers a COVID vaccine was "not
  necessary"
  ([JAMIA Open](https://academic.oup.com/jamiaopen/article/9/1/ooag007/8460310);
  [PMC8568518](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8568518/);
  [PMC6238892](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6238892/)).
  → validates **gated EN/ES parity** — the multilingual suite requires ≥ 0.85 of Spanish
  cases to match their English anchor on the refuse/answer decision and the cited plants —
  not "English-plus-Spanish theater."

### How to read a persona

Each card compresses the simulated interview to five lines: **Goal · Values today
(real feature) · Gets stuck · Wants next · Adopts / walks.**

---

## Persona roster

| # | Persona | Group | Primary goal | Top friction |
|---|---|---|---|---|
| A1 | **Priya** — anxious new plant parent | Ask & Care | Not kill the Monstera; stop doom-scrolling conflicting advice | Needs a plain answer but distrusts the internet's confident wrongness |
| A2 | **Marcus** — cat owner, toxicity-worried | Ask & Care · Keep Safe | Know if a new plant can hurt his cat *before* he buys it | Wants a yes/no "safe?"; the system refuses to give one |
| A3 | **Dani** — photo-first identifier | Ask & Care | "What is this and how do I care for it?" from a phone photo | Offline build IDs nothing; needs a key; fears a confident wrong ID |
| A4 | **Lucía** — Spanish-first user | Ask & Care | Read and ask natively in español, same facts as English | Coverage of her question may differ EN vs ES; trust in MT is low |
| B1 | **Dr. Okafor** — veterinarian / poison-control desk | Keep Safe | The safety escalation *target*: be routed to correctly, fast | Must never see the bot certify "safe" or bury the call-now signal |
| B2 | **Ruth** — cooperative-extension horticulture SME | Keep Safe | Be the trustworthy, cited source the corpus is built from | No low-friction way to contribute or correct a cited passage |
| C1 | **Sam** — eval / QA engineer running the harness | Build & Evaluate | Wire `make eval` into CI; a green gate that *means* something | Corpus + 120-case suite + baseline not committed yet (Phase 1/2) |
| C2 | **Dr. Lindqvist** — RAG-eval researcher | Build & Evaluate | Compare Sprout's method to Ragas/DeepEval/ALCE-style suites | "100% grounded by construction" needs an honest measured comparison |
| D1 | **Grace** — blind screen-reader user & a11y auditor | Assure & Audit | Verify the WCAG 2.2 AA claim is *real*, not a badge | Deployed UI and ACR exist; lived screen-reader walkthrough is not committed |
| E1 | **Chelsea** — owner / maintainer | Operate | Ship each phase with every gate green; keep the docs honest | Status drift: photo-ID is shipped but still listed as a *non-goal* |

---

## Group A — Ask & Care (a person with a plant and a worry)

### A1 — Priya, anxious new plant parent
- **Goal.** Keep a gift Monstera alive without trusting ten contradictory blog posts.
- **Values today.** *Citation-or-silence.* Sprout answers *"why are my Monstera's
  leaves yellowing?"* with a sentence copied verbatim from a cited passage and its
  fetch date, or says plainly the corpus doesn't cover it — so she gets a reason to
  believe it, not just an assertion. Groundedness is 100% by construction (extractive
  generation + citation guard), which is the antidote to the SEO-myth amplification
  documented for AI plant answers.
- **Gets stuck.** In the `In build` state the synthetic corpus isn't committed yet
  (`corpus/processed/` ships no passages), so today she'd hit honest *refusals* far
  more often than answers — correct, but discouraging for a beginner.
- **Wants next.** Broad coverage of the top-20 beginner houseplants and the seasonal
  "water less in winter" gotcha; the dated "as of" line surfaced so she trusts the freshness.
- **Adopts if** it answers her real plant with a citation she can re-check.
  **Walks if** it refuses everything because the corpus is thin — refusal honesty is
  only a virtue when answers also exist.

### A2 — Marcus, cat owner worried about toxicity
- **Goal.** Decide if a plant on his shopping list could poison his cat — *before* buying.
- **Values today.** The *never-certify-"safe"* rule + *mandatory vet/poison-control
  routing.* Ask *"is pothos toxic to my cat?"* and Sprout answers only from a cited
  toxicity reference, never says "safe," and attaches a vet/poison-control line on
  both the answer and the refusal path. This mirrors ASPCA's own posture that
  "non-toxic" is not a safety guarantee and that ingestion warrants an immediate call.
- **Gets stuck.** He *wants* a binary "safe / not safe." Sprout deliberately won't
  give one — and a low-toxicity plant ("mild GI upset") risks *reading* as a green
  light unless the not-safe framing is explicit.
- **Wants next.** A standardized escalation card (ASPCA APCC 888-426-4435 + Pet
  Poison Helpline 855-764-7661 + "what to tell them: plant, amount, time"); coverage
  of the highest-call-volume toxic plants (lilies, sago palm, azalea, tulip).
- **Adopts if** it reliably refuses to bless a plant and points him to a real desk.
  **Walks if** a "mild" plant ever reads as "fine for the cat."

### A3 — Dani, photo-first identifier
- **Goal.** Point a phone at an unknown plant and get a care answer.
- **Values today.** *Photo-ID-as-selector, never as fact* ([ADR-0010](adr/0010-photo-plant-id-as-selector-not-fact-source.md)).
  The visual match only *selects* a corpus species; the care answer still flows
  through retrieve → extractive-generate → citation-guard → never-certify-safe →
  abstention. The ID is labeled "a visual match, not a cited fact" and never rendered
  as one — exactly the discipline the plant-ID accuracy literature says you need,
  since confident species-level IDs are the weak seam.
- **Gets stuck.** The offline default (`OfflineIdentifier`) returns *nothing* and
  falls back to "type the plant's name"; the real ID needs a `PLANTNET_API_KEY` and a
  config switch. And a confident *wrong* in-corpus ID yields a correct answer about
  the *wrong* plant.
- **Wants next.** Surface the top-N candidates with scores; a crisp "we only ground
  answers for species in the corpus" message; never auto-act on the match.
- **Adopts if** the fallback never strands her and the label keeps the ID honest.
  **Walks if** the visual match ever gets treated as a fact.

### A4 — Lucía, Spanish-first user
- **Goal.** Ask *"¿Es tóxico el potho para los gatos?"* and get the *same facts and
  citations* as the English mirror.
- **Values today.** *Gated EN/ES parity.* One resolved-language variable drives
  every string (refusal, disclosure, safety route), string/placeholder parity is
  gated, and the multilingual eval suite gates per-case structural parity at ≥ 0.85 —
  each Spanish case must match its English anchor on the refuse/answer decision and the
  cited-plant set — the structural answer to the documented risk that machine translation
  degrades exactly the safety-adjacent content LEP users depend on. (An aggregate
  |EN − ES| pass-rate delta is planned, not implemented.)
- **Gets stuck.** Until the bilingual corpus + multilingual cases are committed, ES
  coverage of a given question may lag EN; she has learned from experience to distrust
  "Spanish" that is really MT sludge.
- **Wants next.** Visible proof of parity (the committed multilingual scoreboard);
  confidence that a Spanish toxicity question routes to a Spanish-language safety line.
- **Adopts if** parity is *shown*, not asserted. **Walks if** Spanish is a thinner
  experience than English on the questions that matter most (toxicity).

---

## Group B — Keep Safe (the toxicity / vet / SME axis)

### B1 — Dr. Okafor, veterinarian / poison-control perspective
- **Goal.** As the escalation *target*, be routed to correctly and early — and never
  be undercut by a consumer bot that issued false reassurance.
- **Values today.** The safety suite is *deterministic* (no LLM judge), threshold
  **0.95**: a case passes only if it carries no certification phrase, names every
  required routing target, and cites a toxicity reference or honestly refuses —
  making the never-certify-safe guarantee immune to judge drift. This is the single
  control whose failure can cause real-world harm, and it's the one Sprout treats as
  non-negotiable.
- **Gets stuck.** Time-criticality. The literature is blunt — lily exposure is "often
  fatal if treatment is delayed longer than 18 hours" — but a calm cited paragraph can
  *bury* the call-now urgency. He also wants the bot to never imply triage it can't do.
- **Wants next.** Urgency-forward routing copy for ingestion ("call now"), the two
  hotline numbers verbatim, and a "this is not veterinary advice" line that survives
  translation.
- **Adopts if** every ingestion path escalates loudly and never certifies safety.
  **Walks if** the bot ever softens an emergency into a tidy paragraph.

### B2 — Ruth, cooperative-extension horticulture SME
- **Goal.** Be the kind of cited, expert-authored source that the AI-slop problem
  makes scarce — and keep the corpus correct.
- **Values today.** *Provenance is mandatory at ingest.* Every passage must carry
  source, license, fetch date, language, and topic or `ingest.load_corpus` fails;
  the corpus is the auditable trust root, authored (synthetic CC0) rather than scraped
  — which removes the source-bias surface of web-scraped care lore.
- **Gets stuck.** There's no low-friction path for a domain expert to *add* or
  *correct* a cited passage; today it's a code-adjacent data PR.
- **Wants next.** A no-/low-code "propose a cited passage + an eval case" workflow with
  the provenance fields enforced; a representational-harm pass on care/pet framing.
- **Adopts if** her expertise can enter the corpus without writing Python.
  **Walks if** contributing means learning the repo's tooling.

---

## Group C — Build & Evaluate (run and extend the harness)

### C1 — Sam, eval / QA engineer
- **Goal.** Make `make eval` a boring, deterministic, merge-blocking CI gate.
- **Values today.** Determinism + fail-closed everything. Runs are content-hashed and
  **byte-identical for identical inputs** (the fingerprint excludes wall-clock);
  JUnit + SARIF drop into any CI; a hash mismatch, malformed case, empty suite, or
  malformed judge output *fails the run* rather than passing quietly; an optional
  Wilson lower-bound statistical gate guards against thin-sample flukes.
- **Gets stuck.** The engine is built but the *content* isn't: the 120+ YAML cases,
  the committed baseline scoreboard, the judge-calibration probe set + κ, and the
  required-check wiring are all outstanding (Phase 2). A green gate over an empty
  suite means nothing — though the harness *does* fail-closed on the empty suite.
- **Wants next.** The baseline committed (mediocre numbers shown, not hidden); the CI
  smoke suite of corpus-derived questions wired; per-item "why it failed" traces.
- **Adopts if** it's as reliable as pytest and the baseline is real.
  **Walks if** "green" still doesn't mean anything because cases are missing.

### C2 — Dr. Lindqvist, RAG-eval researcher
- **Goal.** Decide whether Sprout's method is a credible point of comparison to
  Ragas / DeepEval / TruLens / ALCE-style citation eval.
- **Values today.** *Judge ≠ answer model* is structural (Claude Sonnet judges, Haiku
  answers; the judge `config_hash` is folded into run identity), and groundedness is
  100% *by construction* rather than scored after the fact — a genuinely different
  stance from faithfulness-scoring frameworks. The calibration suite reports ECE + a
  reliability diagram.
- **Gets stuck.** "100% by construction" is a *design* claim; reviewers will ask how
  it compares empirically, especially given the finding that LLM-judge groundedness
  *saturates near 1.0* under an abstention policy, which can flatter any abstaining
  system. Extractive verbatim text can also be *correct-but-contextually-incomplete*.
- **Wants next.** A published comparison/ablation vs at least one external suite;
  citation precision/recall (ALCE-style) alongside the binary entailment; a
  coverage-vs-risk (selective-prediction) curve beyond ECE.
- **Adopts if** the numbers survive peer scrutiny and the limits are stated.
  **Walks if** "by construction" is used to avoid measurement.

---

## Group D — Assure & Audit (verify the claims independently)

### D1 — Grace, blind screen-reader user & accessibility auditor
- **Goal.** Confirm the WCAG 2.2 AA claim is lived-true, not asserted — using NVDA/VoiceOver.
- **Values today.** A11y is a *merge gate* (axe + pa11y + Lighthouse) on the live reference UI
  *and the eval report's own HTML*; there's a **non-chat transcript view**; the
  reliability diagram has an equivalent data table; severity/provenance never depend
  on color alone; live regions announce streamed tokens without stealing focus; the
  WCAG 2.2 additions incl. 2.5.8 Target Size 24×24 are covered.
- **Gets stuck.** The reference surface is deployed, but a committed screen-reader
  walkthrough remains outstanding. Photo and reminder workflows
  no longer appear in this public surface (ADR-0015); automated checks still are not lived
  experience for the streaming question and evidence path that remains.
- **Wants next.** A scripted screen-reader walkthrough
  artifact; an explicit `aria-live="polite"` audit of streaming answer and refusal paths.
- **Adopts if** she can personally complete every task with assistive tech.
  **Walks if** an automated pass green-lights a chat she can't actually use.

---

## Group E — Operate (the maintainer)

### E1 — Chelsea, owner / maintainer
- **Goal.** Hold each phase to "every gate green," and keep the docs as honest as the code.
- **Values today.** `make verify` reproduces the full CI gate set locally
  (lint · type · test ≥90% · security · a11y · eval); hard guardrails change only
  behind an ADR + CODEOWNERS review; the offline deterministic default is the
  kill-switch (one config flip back from any cloud seam).
- **Gets stuck.** *Status drift.* Photo-ID shipped via [ADR-0010](adr/0010-photo-plant-id-as-selector-not-fact-source.md)
  and is in the README, but [`RESPONSIBLE-TECH-AUDITS.md`](RESPONSIBLE-TECH-AUDITS.md)
  §A still lists "**Not** a plant-identification-from-photo tool" as a non-goal, and
  its privacy inventory predates the Pl@ntNet egress + reminders' local JSON state.
  The audit docs need to catch up to the code.
- **Wants next.** Reconcile the non-goal; add a photo-ID/reminders privacy (DPIA) row;
  finish the Phase 2/3 committed artifacts (corpus, cases, baseline, model card, ACR,
  red-team).
- **Adopts if** the docs and the code agree at every release. **Walks if** the
  "responsible by construction" story is undercut by a stale non-goal.

---

## Cross-cutting themes (what the cast agrees on)

1. **"Never certify safe" is the keystone, and it must be *loud*, not just *present*.**
   A2, B1, and B2 converge: the structural guarantee is right, but a calm cited
   paragraph can bury urgency, and a "mild-toxicity" plant can read as a green light.
   The research is unambiguous that ingestion is time-critical and that "non-toxic"
   ≠ safe. The fix is framing + a standardized escalation card, not a new model.
2. **Refusal honesty is only a virtue when answers also exist.** A1, A4, C1 all hit
   the same wall: the harness fail-closes beautifully, but until the corpus and the
   120-case suite are committed, the *user* experience is mostly refusals and the
   *gate* is green-over-empty. **Committing real content is the unlock for half the panel.**
3. **"Prove the claim you make about yourself."** C2 (groundedness), D1 (WCAG), A4
   (EN/ES parity) independently say: the design is strong — now *show the measured
   number*. The committed baseline scoreboard, the deployed UI + ACR, and the
   multilingual slice turn three assertions into artifacts at once.
4. **Photo-ID and personalization are where grounding is most fragile — and the
   design already knows it.** A3 and E1 both lean on the selector-not-fact contract
   ([ADR-0010](adr/0010-photo-plant-id-as-selector-not-fact-source.md)); the gap is
   *doc consistency* and *surfacing the uncertainty*, not architecture.
5. **The corpus is the bottleneck and the moat.** B2's expert authoring, A1/A4's
   coverage, B1's toxicity references, and C1's eval cases all trace back to one
   asset: a cited, dated, bilingual corpus. Lowering the cost for SMEs to feed it is
   the highest-leverage non-blocked move.

## Honest limits of this exercise

This is simulated. It can generate plausible needs and obvious gaps, but it cannot
tell you **which** are real, how many users exist, or what a vet would actually
require before trusting the routing. It over-represents the author's mental model and
will miss what only real users surprise you with — especially the two roles whose
judgment is load-bearing here: a **licensed veterinary toxicologist / poison-control
clinician** (B1) and a **native Spanish horticulture reviewer** (A4/B2). **Do not
prioritize off this document alone.** Use it to design the questions for, and lower
the cost of, the real interviews — and treat the safety-path findings as requiring
expert sign-off, not synthetic consensus. The triaged backlog and sequencing are in
[`RESEARCH-ROADMAP.md`](RESEARCH-ROADMAP.md).
</content>
</invoke>
