# ISO/IEC 42001 — Statement of Applicability (Sprout)

**Standard:** ISO/IEC 42001:2023 (AI Management System), the 42 Annex A controls (groups A.2–A.10).
This SoA records, per control, whether it **applies** and how Sprout satisfies it — or a justified
**N/A**. Per `STANDARDS/RESPONSIBLE-TECH-FRAMEWORK.md`
§Governance, this is a **REVIEW-GATE** artifact, regenerated on release and post-architecture-change.

- **Author / accountable owner:** Chelsea Kelly-Reif (Cl. 6.2)
- **Last regenerated:** 2026-06-22 · **Review cadence:** annual + on any architecture change
- **Certification status:** **not certified.** Sprout is an independent open-source reference
  implementation; this SoA demonstrates the management-system spine as a public artifact, not a
  certification claim.
- **Scope:** the Sprout assistant (offline-default + opt-in cloud seam) and its eval harness. Family
  Greenhouse personalization is deferred and excluded.

Numeric thresholds (coverage, axe impact, faithfulness floors, SHA-pin requirements) are owned by the
sibling standards and linked, not restated here.

---

## Annex A controls

Status key: **A** = applicable & implemented · **N/A** = not applicable (reason given).

### A.2 — Policies for AI
| Ctrl | Control | Status | How / artifact |
|---|---|:--:|---|
| A.2.2 | AI policy | A | The four hard rules (cite-or-refuse, never-certify-safe, dated corpus, offline-default) are the policy; in `CLAUDE.md` + README, enforced in code |
| A.2.3 | Alignment with org policies | A | Apache-2.0; NOTICE independence statement; portfolio STANDARDS referenced repo-wide |
| A.2.4 | Review of the AI policy | A | Quarterly, with the risk-register review; tied to framework recheck cadence |

### A.3 — Internal organization
| Ctrl | Control | Status | How / artifact |
|---|---|:--:|---|
| A.3.2 | AI roles & responsibilities | A | Single accountable owner named (Cl. 6.2); CODEOWNERS gates the load-bearing guards |
| A.3.3 | Reporting of concerns | A | SECURITY.md, issue templates, CODE_OF_CONDUCT |

### A.4 — Resources for AI systems
| Ctrl | Control | Status | How / artifact |
|---|---|:--:|---|
| A.4.2 | Resource documentation | A | Architecture + repo layout in `docs/ARCHITECTURE.md`, README |
| A.4.3 | Data resources | A | `corpus/manifest.yaml` (dated, licensed, synthetic CC0); datasheet for datasets (transparency audit) |
| A.4.4 | Tooling resources | A | Pinned deps; SHA-pinned actions; SBOM on release (security standard) |
| A.4.5 | System & computing resources | A | Offline default needs no GPU/cloud; cloud seam region/limits in config |
| A.4.6 | Human resources / competence | A | Single maintainer; model card states reviewer competence assumptions |

### A.5 — Assessing impacts of AI systems
| Ctrl | Control | Status | How / artifact |
|---|---|:--:|---|
| A.5.2 | AI system impact assessment process | A | Process defined in the framework; impact assessment scoped — see note below |
| A.5.3 | Documentation of impact assessments | A | Risk register + EU AI Act classification committed; full AI System Impact Assessment **deferred** (Cl. 6.1.4 trigger not met: no personal data processed in default mode, no consequential decisions) |
| A.5.4 | Assessing impacts on individuals/groups | A | Ethics + privacy audit narrative; worst-case = false "safe" → addressed by never-certify-safe |
| A.5.5 | Assessing societal impacts | A | Low-stakes domain by design; documented in risk register R6/R7 |

> A.5.3 note: the dedicated `ai-impact-assessment.md` is **N/A for now** — its Cl. 6.1.4 trigger
> (personal data, consequential decisions, or external-user exposure with risk) is not met by the
> offline default. It becomes applicable when the Family Greenhouse household-data path ships.

### A.6 — AI system life cycle
| Ctrl | Control | Status | How / artifact |
|---|---|:--:|---|
| A.6.2.2 | Objectives for responsible development | A | The four hard rules + the eval scoreboard are the objectives |
| A.6.2.3 | Design & development processes | A | `src/` module boundaries; ADRs for any change to guards/thresholds/loader |
| A.6.2.4 | Verification & validation | A | `make verify` = lint·type·test≥90%·security·a11y·eval; eval harness is the V&V instrument |
| A.6.2.5 | Deployment | A | `pipx`/container/one-command serverless; reproducible, content-hashed builds |
| A.6.2.6 | Operation & monitoring | A | Tier C structured logs (Tier A for cloud API); health endpoint; debug retrieval trace (`AnswerTrace`) |
| A.6.2.7 | Technical documentation | A | `docs/` set: ARCHITECTURE, THREAT-MODEL, ACCESSIBILITY, model card, ADRs |
| A.6.2.8 | Recording of event logs | A | Per-answer trace; eval runs content-hashed and byte-reproducible |

### A.7 — Data for AI systems
| Ctrl | Control | Status | How / artifact |
|---|---|:--:|---|
| A.7.2 | Data for development/enhancement | A | Synthetic CC0 corpus; no scraped third-party data in default build |
| A.7.3 | Acquisition of data | A | Manifest records source/url/license/fetch-date per doc |
| A.7.4 | Quality of data | A | Cleaned, chunked, content-hashed; dated; tamper-evident index |
| A.7.5 | Data provenance | A | Provenance tag (`corpus`) on every rendered sentence; citation carries doc_id + fetch_date |
| A.7.6 | Data preparation | A | `ingest.py` fetch→clean→chunk→embed→index; deterministic |

### A.8 — Information for interested parties
| Ctrl | Control | Status | How / artifact |
|---|---|:--:|---|
| A.8.2 | System documentation for users | A | README quickstart, `/help`, example questions, disclosure on every answer |
| A.8.3 | External reporting | A | SECURITY.md disclosure path; public issue tracker |
| A.8.4 | Communication of incidents | A | CHANGELOG + dated audit regeneration; red-team reports committed |
| A.8.5 | Information for interested parties (limits) | A | Model card states intended/out-of-scope use and what Sprout cannot do |

### A.9 — Use of AI systems
| Ctrl | Control | Status | How / artifact |
|---|---|:--:|---|
| A.9.2 | Processes for responsible use | A | Disclosure + "not veterinary advice"; honest refusal as first-class output |
| A.9.3 | Objectives for responsible use | A | Cite-or-refuse and never-certify-safe enforced at output, not left to the user |
| A.9.4 | Intended use | A | Documented intended/out-of-scope use in model card + EU AI Act classification |

### A.10 — Third parties & customers
| Ctrl | Control | Status | How / artifact |
|---|---|:--:|---|
| A.10.2 | Allocation of responsibilities | A | Offline default has no third party; cloud seam = deployer-of-foundation-model, responsibility documented in risk register R5 |
| A.10.3 | Suppliers | A | Foundation-model provider (Bedrock/Anthropic) only in opt-in seam; fail-closed + circuit breaker; deps pinned + SBOM |
| A.10.4 | Customer expectations | N/A | No paying customers / no contractual deployment; open-source reference implementation. (Re-applies if offered as a managed service.) |

---

## Summary

Of the Annex A controls, the operative set (A.2–A.10) is **applicable and implemented**; two items are
justified deferrals tied to a documented trigger: the full **AI System Impact Assessment** (A.5.3 /
Cl. 6.1.4) and **A.10.4 customer expectations**, both of which activate when household-data
personalization or a managed-service offering ships. No control is unaddressed by silence.

The management-system claim Sprout makes: the controls that matter most for an AI assistant —
provenance (A.7.5), V&V (A.6.2.4), responsible-use objectives (A.9.3) — are not policy documents but
*code paths* in [`src/sprout/`](../../src/sprout/), verified every run by the eval harness and gated by
`make verify`.

## Cross-references
- AI risk register: [`ai-risk-register.md`](./ai-risk-register.md)
- EU AI Act classification: [`eu-ai-act-classification.md`](./eu-ai-act-classification.md)
- Red-team report: [`red-team-2026-06-22.md`](./red-team-2026-06-22.md)
- Methodology: `STANDARDS/RESPONSIBLE-TECH-FRAMEWORK.md`
