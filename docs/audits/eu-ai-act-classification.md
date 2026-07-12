# EU AI Act Classification — Sprout

**Regulation:** (EU) 2024/1689 (the AI Act). Full high-risk application Aug 2, 2026; GPAI obligations
live since Aug 2025; Annex III conformity deadline Dec 2, 2027. Per
`STANDARDS/RESPONSIBLE-TECH-FRAMEWORK.md` §Governance,
the obligation here is the **decision artifact**, not certification: silence is non-conformant, a
written classification is conformant.

- **Author / accountable owner:** Chelsea Kelly-Reif
- **Last regenerated:** 2026-06-22 · **Re-run trigger:** any material change to model, prompt,
  architecture, or intended use; and on each AI Act enforcement phase-gate.

---

## Classification (the explicit line)

> **Sprout is a minimal-risk AI system under Reg. (EU) 2024/1689.** It is **not** an Annex III
> high-risk system, it is **not** a prohibited practice (Art. 5), it is **not** a general-purpose AI
> model (GPAI) — Sprout *uses* a foundation model in an opt-in cloud seam, it does not place one on
> the market. **Training compute = 0** (no model is trained or fine-tuned), so the 10^25-FLOP
> systemic-risk GPAI threshold is not engaged. The only obligations that attach are the **Art. 50
> transparency** duties, which are met by disclosure + the model card.

---

## Why — step by step

### 1. Is it a "prohibited practice"? (Art. 5) — No
Sprout does no subliminal manipulation, social scoring, biometric categorisation, emotion inference,
or untargeted face-scraping. It answers houseplant-care questions from a cited corpus. **Not prohibited.**

### 2. Is it "high-risk"? (Art. 6 + Annex III) — No
Annex III enumerates eight high-risk domains: biometrics; critical infrastructure; education/vocational
training; employment/worker management; access to essential private/public services (incl. credit,
benefits, emergency dispatch); law enforcement; migration/asylum/border; administration of justice and
democratic processes. **Sprout touches none of them.** It is a consumer information tool about
houseplants. It is also not a safety component of a product covered by the Annex I harmonisation
legislation. **Not Annex III; not high-risk.**

> Note on the toxicity feature: answering "is this plant toxic to my cat?" is *adjacent* to safety, but
> it is consumer horticultural information, not a regulated safety component, medical device, or an
> Annex III service. Sprout's design reinforces this: it **never certifies a plant safe**, routes
> ingestion questions to a vet / poison-control line, and labels every answer "not veterinary advice."
> The feature lowers risk; it does not create a high-risk classification.

### 3. Is it a GPAI model? (Art. 51–55) — No
A GPAI model is a model placed on the market that displays significant generality. Sprout **places no
model on the market**. In its default mode it ships a deterministic retriever + extractive generator
(`HashingEmbedding` + BM25 + `ExtractiveGenerator`) — no foundation model at all. In its opt-in cloud
seam it is a *downstream deployer* calling a third party's hosted Claude model; the GPAI obligations
fall on that upstream provider, not on Sprout. **Not a GPAI provider.**

### 4. Training compute / systemic-risk threshold — 0 FLOP
Sprout trains and fine-tunes **nothing**. There is no training run, so the 10^25-FLOP systemic-risk
presumption for GPAI (Art. 51) is structurally inapplicable. The environmental footprint of the default
mode is effectively zero (offline, no GPU inference); the opt-in cloud seam's per-token inference is
recorded in the model-card CO2 row (NIST AI 600-1 Risk 5).

---

## The obligations that *do* apply: Art. 50 transparency (minimal-risk)

For a minimal-risk system, the AI Act imposes voluntary codes plus the **Art. 50** transparency duties
where AI interaction or AI-generated content is involved. Sprout meets them by disclosure, not by a
new mechanism:

| Art. 50 duty | How Sprout meets it | Where |
|---|---|---|
| Inform users they are interacting with an AI system | "Reference implementation" banner on the UI; README states it plainly; the assistant is self-evidently an AI chat tool | README, UI banner |
| Label AI-generated / machine-processed content | Every answer carries a disclosure string ("Answers are drawn only from a dated, cited plant-care corpus. This is not veterinary advice.") in EN and ES; every claim carries an inline citation + "as of" date | `PromptConfig.disclosure_by_lang`, `Answer.disclosure` |
| Make limitations understandable | Model card states intended use, out-of-scope use, and what the system cannot do; honest refusals are first-class output | `docs/cards/model-card.md`; refusal path in `answer.py` |
| Accessibility of the disclosure | Disclosure rendered in the WCAG 2.2 AA UI and the non-chat transcript view | Accessibility audit / ACR |

Machine-readable content labeling (Art. 50 §2, deep-fake/synthetic-media marking) is **not engaged** —
Sprout generates extractive text grounded to a cited corpus, not synthetic media; it carries
human-readable disclosure regardless.

---

## Net obligations and conformance

| Question | Answer |
|---|---|
| Prohibited (Art. 5)? | No |
| High-risk (Art. 6 / Annex III)? | **No** |
| GPAI model provider (Art. 51–55)? | **No** (deployer of a third-party model in an opt-in seam) |
| GPAI with systemic risk (≥10^25 FLOP)? | **No** — training compute = 0 |
| Limited-risk transparency (Art. 50)? | **Applies** — met via disclosure + model card |
| Conformity-assessment package (Art. 17/18/47)? | **N/A** — only required for Annex III high-risk |
| **Overall classification** | **Minimal-risk** |

**Conformance statement.** No conformity assessment, CE marking, EU database registration, or
fundamental-rights impact assessment is required. Sprout nonetheless ships the transparency artifacts
(model card, disclosure strings, citation provenance, accessibility statement) and the broader
responsible-AI audit set voluntarily — the point of the project is to demonstrate the discipline a
buyer audits to, even where the law does not compel it.

## Cross-references
- AI risk register (NIST AI RMF MAP): [`ai-risk-register.md`](./ai-risk-register.md)
- ISO 42001 SoA: [`iso42001-soa.md`](./iso42001-soa.md)
- Model card: `docs/cards/model-card.md`
- Methodology + current framework versions: `STANDARDS/RESPONSIBLE-TECH-FRAMEWORK.md`
