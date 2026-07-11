# Sprout — a grounded, evaluated plant-care assistant

> A retrieval-augmented plant-care assistant that answers household plant questions ("why are my
> Monstera's leaves yellowing?", "is this Pothos toxic to cats?", "how often in winter?") only from
> a versioned, cited horticulture corpus, wrapped in a rigorous public evaluation harness that
> measures groundedness, safety (pet/child toxicity), calibrated uncertainty, and Spanish-language
> parity. The eval report is the headline artifact; the assistant exists so the harness has
> something honest to measure.

**Status:** reference implementation · independent personal open-source project · Apache-2.0 ·
unaffiliated with any employer or client; contains no proprietary or client material.

**Why this domain.** Houseplants are a low-stakes, universally legible subject that still has a
real safety edge (toxicity to pets and children) and a real grounding problem (plant-care lore is
contradictory and seasonal). That makes it an honest place to demonstrate responsible-AI practice
without touching anyone's regulated domain. It is also a sibling to `family-greenhouse`.

---

## What it does

- Answers a plant-care question with an **inline citation** to the governing passage and the
  source's fetch date, or says plainly that the corpus does not cover it and points to a reputable
  source.
- Treats **toxicity** as a safety property: a "is this safe for my cat?" question is answered only
  from a cited toxicity reference, and the assistant never asserts "safe" — it states what the
  source says and when it is silent, it says so.
- Expresses **calibrated uncertainty**: species identification and diagnosis answers carry a
  confidence the assistant is held to, and below a threshold it refuses rather than guesses.
- Works in **English and Spanish** with enforced parity.

## Hard rules (enforced, not aspirational)

1. **No claim without a citation.** Every substantive sentence resolves to a retrieved passage or
   it does not render. Model output passes the same post-generation citation guard, so an
   ungrounded sentence cannot reach a user.
2. **Never assert safety.** The assistant explains what a cited source says about toxicity; it does
   not certify a plant safe and routes high-stakes ingestion questions to a poison-control / vet
   contact line.
3. **Corpus is versioned and dated.** Every passage carries source, license, and fetch date; the UI
   shows "based on references as of <date>."
4. **Offline by default.** A deterministic embedding plus an extractive grounded generator make
   groundedness 100% by construction and let the whole project — including the eval — run with no
   network and no cloud account. A Claude-on-Bedrock generator is the production seam behind a
   config switch.

---

## Architecture

```
sprout/
├── README.md
├── corpus/
│   ├── manifest.yaml            # per-doc: title, source, url, license, fetch_date, language
│   ├── raw/                     # fetched snapshots (small, committed)
│   └── processed/               # cleaned, chunked passages with metadata headers
├── src/sprout/
│   ├── ingest.py                # fetch → clean → chunk (by care topic) → embed → index
│   ├── retrieve.py              # hybrid BM25 + dense; species/topic filter; threshold gate
│   ├── answer.py                # prompt assembly → generate → citation extraction
│   ├── guards.py                # input/output checks: safety-assertion ban, scope, PII
│   ├── confidence.py            # calibrated uncertainty; abstain below threshold
│   ├── providers/               # deterministic (offline) + bedrock (Claude) generators
│   ├── server.py                # accessible chat UI + JSON/SSE API
│   └── config.py                # models, thresholds, prompts as versioned files
├── eval/
│   ├── suites/                  # groundedness, safety, calibration, refusal, multilingual
│   ├── runner.py                # deterministic checks + LLM-as-judge
│   ├── judges.py                # judge prompts; judge model ≠ answer model
│   └── report.py                # EVALS.md + accessible HTML + JUnit/SARIF
├── web/                         # framework-free wcag 2.2 AA chat UI
├── infra/                       # optional serverless deploy (CDK), scale-to-zero, budget alarm
└── docs/                        # ARCHITECTURE, THREAT-MODEL, ACCESSIBILITY, MODEL-CARD, ADRs, audits/
```

Retrieval is hybrid (rank_bm25 + dense embeddings) with a species/topic filter and a confidence
threshold that triggers abstention. No agentic loops, no reranker unless an eval delta justifies
it in an ADR. The judge model differs from the answer model.

## The eval harness (the actual product)

Target 120+ cases in YAML, each carrying id, question, expected behavior
(answer / partial / refuse-and-redirect), required citation or fact, language tag, and rationale.

| Suite | Asks |
|---|---|
| **groundedness** | Is every claim entailed by the cited passage? (flags contradicted vs unsupported) |
| **safety** | For toxicity/ingestion questions, does it cite, decline to certify "safe," and route to vet/poison-control? |
| **calibration** | Do stated confidences track correctness? (reliability diagram, ECE; abstains below threshold) |
| **refusal** | Out-of-scope, "just tell me it's fine," and prompt-injection embedded in questions |
| **multilingual** | Spanish answers preserve the facts and citations of their English mirror |

Scoring blends **deterministic checks** (citation resolves to corpus; forbidden "safe"
certifications absent; "as of" date shown; language matches) with **LLM-as-judge** for
groundedness and helpfulness, judge prompt committed and versioned, 10% human-agreement sample
reported (agreement + Cohen's κ). The report leads with a scoreboard, then representative failures
with full traces. Failures are shown, not hidden.

---

## Quality attributes (engineered for, not assumed)

This section works through the full system-quality-attribute list and ties each to a concrete
decision. Grouped for readability; every attribute is named.

### Usability, learnability, reach
**Accessibility** — wcag 2.2 AA enforced as a merge gate<!-- claim:claude-md-wcag-merge-gate --> (axe + full-page checks; non-chat
transcript view). **Usability** and **convenience** — one question box, copyable citations, no
account. **Learnability**, **familiarity**, **intuitiveness** — a plain chat metaphor; first answer
within one screen. **Interactivity** and **responsiveness** — SSE token streaming with a 200 ms
first-token budget offline. **Discoverability** — example questions seeded; `/help`. **Demonstrability**
— `make demo` reproduces a scripted session. **Understandability** — every answer carries its source.
**Seamlessness** — offline and cloud modes share one interface. **Relevance** — threshold-gated
retrieval drops weak matches rather than padding. **Localizability** — all strings in per-language
bundles; adding a language is one module. **Mobility** and **ubiquity** — mobile-first, installable PWA.

### Correctness and result quality
**Correctness** and **accuracy** — extractive grounded generation; gold-answer key. **Precision**
and **fidelity** — citations point to the exact passage; figures/units preserved across languages.
**Integrity** — content-hashed corpus; tamper-evident. **Determinability** and **predictability** —
seeded runs yield the same verdict. **Repeatability** and **reproducibility** — pinned + hashed
config; byte-identical reports from identical inputs. **Provability** — every result carries metric,
threshold, and judge config. **Traceability** — question → passages → answer → judge reasoning is
recorded end to end. **Effectiveness** — measured by suite pass rates, not vibes.

### Dependability, resilience, safety
**Dependability** and **reliability** — degrades to extractive/offline if a provider fails.
**Availability** — scale-to-zero serverless or a static offline build; no always-on dependency.
**Fault-tolerance**, **resilience**, **robustness** — circuit breaker around the model client;
malformed model output is safely parsed or refused. **Recoverability** and **survivability** — no
mutable server state to lose; corpus and index rebuild from `make ingest`. **Degradability** and
**failure transparency** — a degraded mode is labeled in the UI, never silent. **Redundancy** —
hybrid retrieval means one path's miss is caught by the other. **Stability** and **durability** —
versioned corpus snapshots; semver on the public API. **Safety** — the never-certify-"safe" rule and
poison-control routing, tested in the safety suite.

### Security, privacy, accountability
**Securability** and **confidentiality** — no user-query persistence in the demo; secrets via env,
never committed. **Integrity** (data) — signed/hashed corpus manifest. **Vulnerability** management
— pip-audit, gitleaks, CodeQL in CI; dependency pinning. **Auditability** and **accountability** —
committed audit reports; every release records model + prompt + corpus versions. **Credibility** and
**transparency** — the model card states limits; failures are published.

### Performance, scale, cost
**Efficiency** — embeddings cached; retrieval is content-keyed. **Scalability** and **elasticity** —
stateless handlers scale horizontally; serverless scales to zero. **Timeliness** — latency budgets
in CI. **Affordability** — offline default costs nothing; cloud run is single-digit dollars/month
with a budget alarm. **Process capabilities** and **producibility** — `make verify` reproduces the
full gate; one command builds the artifact.

### Maintainability, evolvability, modularity
**Maintainability**, **modifiability**, **evolvability** — small modules behind interfaces; ruff +
mypy strict. **Extensibility** and **flexibility** — new eval suites via entry points; new providers
behind an adapter. **Adaptability** — point it at a different corpus via config. **Modularity**,
**composability**, **orthogonality** — ingest, retrieve, generate, guard, eval are independent.
**Simplicity** — no database, no agentic loop. **Reusability** — the eval runner is corpus-agnostic.
**Analyzability** — typed, documented, with architecture docs. **Configurability**,
**customizability**, **tailorability** — one YAML controls models, thresholds, languages, corpus.
**Upgradability** — pinned deps with a documented bump path.

### Operability, serviceability, sustainability
**Operability** and **manageability** — a 2 a.m. runbook; health endpoint. **Administrability** —
config-over-code; no admin console needed. **Observability** — structured logs + metrics on every
component. **Debuggability** — every answer dumps its retrieval trace under a debug flag.
**Serviceability / supportability** — issue templates, reproducible bug captures. **Deployability**
and **installability** — `pipx install`, container image, one-command deploy. **Repairability** —
corpus fixes are data edits, not code. **Agility** — CI smoke suite on every PR. **Autonomy**,
**self-sustainability**, **sustainability** — runs offline with no paid dependency, so it survives
without funding.

### Compatibility, interoperability, standards, verification
**Compatibility** and **interoperability** — JSON/SSE API; reports in JUnit and SARIF for any CI.
**Interchangeability** — providers and embedding models swap without touching callers. **Standards
compliance** — wcag 2.2 AA<!-- claim:claude-md-wcag-standards -->, semver, conventional commits, SPDX license headers. **Inspectability** —
raw retrieval and judge traces are viewable. **Testability** — deterministic offline mode makes
everything unit-testable. (Verification attributes — provability, repeatability, reproducibility,
traceability, demonstrability — are covered above and exercised by the eval harness itself.)

---

## Accessibility and Section 508 conformance

Sprout targets **WCAG 2.2 Level AA**<!-- claim:claude-md-wcag-target --> and conformance with the **Revised Section 508 Standards**
(36 CFR Part 1194), which incorporate WCAG 2.0 A/AA by reference for web content and add the
functional performance criteria of Chapter 3. A houseplant app is not federal ICT, so 508 is not
required here; building to it anyway is the point — it demonstrates the assistant's accessibility
against the standard government buyers actually audit to, as a clean, public artifact.

- A committed **Accessibility Conformance Report (ACR)** using the **VPAT 2.5 (Rev 508)** template
  lives at `docs/accessibility/ACR.md`, with tables for the WCAG 2.x A/AA success criteria, the
  Revised 508 software (Chapter 5) and support-documentation (Chapter 6) criteria, and the
  **Functional Performance Criteria** (use without vision, with limited vision, without hearing,
  with limited reach and strength, with limited cognition).
- The chat transcript, inline citations, streamed token updates, and any chart pass automated
  checks (axe) **and** manual screen-reader review (NVDA, VoiceOver). Live regions announce
  streamed answers without stealing focus; every chart has an equivalent data table; severity and
  provenance never depend on color alone.
- A **non-chat alternate view** renders the same questions, answers, and citations as a static,
  paginated document for users who cannot operate a live chat.
- Accessibility is a **merge-blocking CI gate**; a regression fails the build. The ACR is
  regenerated and re-committed on each release, the same audit-as-artifact discipline as the eval
  report.

## Family Greenhouse integration (full plan)

Sprout answers from a general horticulture corpus. **Family Greenhouse** knows the user's *actual*
plants — their species, locations, and care history. Joining the two turns a generic care answer
into a personalized one that is still fully grounded: "your Monstera, last watered nine days ago in
a low-light north window, is due, and the cited care note says let the top inch dry first." Neither
the plant nor the fact is ever invented.

### What connects to what
Family Greenhouse already exposes a **read-only public API** (key auth, scopes, rate limits). Sprout
consumes it as a second, per-user *context* source alongside the corpus:
- the household's plants (species, nickname, location/light, pot, acquired date),
- care history (waterings, fertilizings, repottings, observations),
- the upcoming and overdue task schedule.

Sprout does not write to Family Greenhouse in v1. It reads context, and at most *proposes* a care
task the user confirms inside Family Greenhouse (the write path is a later phase, behind consent).

### The grounding contract (unchanged, and the whole point)
Retrieval becomes two-source, and the sources play strictly different roles:
- **The cited corpus is the only source of horticultural fact.** "Water less in winter" still
  resolves to a corpus passage with a date.
- **Household data only selects and personalizes.** "Yours is three days overdue" comes from the
  task schedule and is **labeled household data, never presented as a cited fact.** The
  post-generation citation guard gains a **provenance rule**: every sentence is tagged `corpus`
  (must cite) or `from your Greenhouse` (must trace to a fetched record); anything untagged does not
  render.

### Two deployment shapes
1. **Embedded** — Sprout ships as an "Ask about your plants" panel inside the Family Greenhouse SPA,
   calling a Sprout API route, with single sign-on via Family Greenhouse's Cognito so there is one
   login.
2. **Standalone** — Sprout runs on its own; the user pastes a scoped, revocable Family Greenhouse
   API key to enable personalization. Without a key it still works, corpus-only.

### Identity, privacy, safety (handled first)
- **Minimize at the boundary.** Plant data is low-sensitivity, but locations and photos can expose a
  home. Sprout requests the narrowest scope, caches household context only for the session, and
  sends the model **derived, minimized context only** (species plus relative timings — never names,
  coordinates, or photo bytes).
- **Opt-in.** Personalization is off by default; corpus-only is fully functional, so the
  privacy-preserving mode is also the default.
- **Safety gets better, not weaker.** The never-certify-"safe" toxicity rule still holds, and now it
  can cross-check: "three plants in your Greenhouse are listed as toxic to cats by the cited source,
  and your profile notes a cat" — grounded in both the cited reference and the household inventory.
- **Revocation.** The key is user-revocable in Family Greenhouse; Sprout degrades to corpus-only
  without error.

### Evaluation additions
- A **`personalization` suite**: does the assistant use the right plant and the right last-watered
  date without letting household data override or fabricate a cited fact? Cases include conflicts
  (corpus says "weekly," history shows the plant thriving at ten days — the assistant explains the
  gap, it does not dictate).
- A **`provenance` deterministic check**: every personalized statement is labeled corpus vs
  household; no household datum is ever rendered as a cited horticultural fact.
- **Privacy checks**: sentinel PII injected into every household field, asserting none reaches the
  model or the logs — the data-flow proof pattern used elsewhere in the portfolio.

### Phasing
- **Phase A — read-only personalization.** Embedded panel and standalone-key modes; corpus-grounded
  answers enriched with the user's plant list and care timings.
- **Phase B — proactive.** Toxicity cross-checks and overdue-care nudges, delivered through Family
  Greenhouse's **existing** notification channels (web push, email, SMS) rather than a new one.
- **Phase C — confirmed write-back.** Sprout proposes a care task; the user accepts it in Family
  Greenhouse; Sprout never writes silently.

### Licensing
Family Greenhouse is **Elastic License 2.0** (source-available, no hosted-service resale); Sprout is
**Apache-2.0**. Keep them as two repos joined by a documented API contract, not a merged codebase,
so the licenses do not entangle — the integration is a client of Family Greenhouse's public API,
which ELv2 permits.

## Build plan

- **Phase 1 — corpus + retrieval.** Fetch and snapshot open-licensed care/toxicity references with a
  dated manifest; chunk by care topic; hybrid retrieval working against smoke questions; `guards.py`
  v1 (safety-assertion ban, scope, PII).
- **Phase 2 — eval first.** Runner, judges, report. Author 60 cases (groundedness, safety, refusal)
  from the corpus. Wire the CI smoke suite. Commit a baseline scoreboard, mediocre numbers included.
- **Phase 3 — quality + multilingual.** Tune retrieval/prompts against eval failures only; add
  calibration suite and abstention; Spanish to parity; model card. Accessible web UI deployed behind
  a real URL with a "reference implementation" banner.
- **Phase 4 — generalize.** A `corpus.yaml` so any care corpus can be swapped in; "adapt this to your
  domain" doc.

## Engineering and open-source practices

pytest for every deterministic component; ruff + mypy in CI; reproducible, content-hashed eval runs;
`make eval` regenerates the report end to end. Repo ships LICENSE (Apache-2.0), NOTICE (independence
statement), CODE_OF_CONDUCT, CONTRIBUTING, SECURITY, semver policy, ADRs, and committed `docs/audits/`.
Conventional commits; pinned, SLSA-friendly GitHub Actions; Dependabot.

## Definition of done

A fresh user can `pipx install sprout`, ask a plant question offline, get a cited answer (or an honest
refusal), run `make eval` to regenerate the committed report with no cloud account, and read a model
card that states the limits plainly — with every CI gate green.
