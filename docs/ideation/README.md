# Ideation — large-scale fixes and expansions (drafted 2026-07-01)

> **What this folder is.** A structured ideation pass over Sprout as it exists on
> 2026-07-01: deep structural fixes and expansion bets that the existing planning
> documents do **not** already contain. It was produced by reading the full repo —
> source, tests, CI, committed audit artifacts — not by restating the specs.

## How this relates to the existing planning documents

Sprout already has two planning layers, and this folder is deliberately a third:

- [`docs/ROADMAP.md`](../ROADMAP.md) — the phased build plan, metrics ledger, and
  conformance declarations (Phases 1–4, currently Phase 3).
- [`docs/RESEARCH-ROADMAP.md`](../RESEARCH-ROADMAP.md) +
  [`docs/USER-RESEARCH.md`](../USER-RESEARCH.md) — the 2026-06-30 synthetic-stakeholder
  pass, whose backlog items are R1–R10 and E1–E11.

**Nothing here restates an item from those documents.** Where an idea builds on an
existing item (e.g., extends ADR-0010 or goes beyond E11), it references that item by ID
and says exactly what the delta is. Several fixes below exist *because* of what the
existing documents claim: they close gaps between what the docs assert and what the code
and CI actually enforce — which is itself the portfolio's honesty-as-a-feature ethos
applied to Sprout's own paperwork.

## Index

| File | Contents |
|---|---|
| [`01-deep-dive.md`](01-deep-dive.md) | Current-state assessment from a full read: architecture map with file paths, genuine strengths, observed structural debt, portfolio position |
| [`02-large-scale-fixes.md`](02-large-scale-fixes.md) | FIX-01 … FIX-13 — deep structural fixes (correctness, safety, security, i18n, performance, operability) |
| [`03-expansions.md`](03-expansions.md) | EXP-01 … EXP-17 — expansions in three horizons (deepen the core / adjacent / transformative) |
| [`04-impact-and-sequencing.md`](04-impact-and-sequencing.md) | Impact×effort matrix over all IDs, dependencies, a Now/Next/Later sequence beyond the existing roadmaps, and the human/SME/real-data gates |

## Honest framing

These are **ideas for evaluation, not commitments.** They have not been costed against
real maintainer capacity, none has an ADR, and several are explicitly gated on expertise
this repo does not yet have access to (a licensed veterinary toxicologist, a
poison-control clinician, a native-Spanish horticulture reviewer). Two constraints are
treated as inviolable throughout:

1. **Veterinary-toxicologist / clinician review is required before shipping any safety
   copy.** No item below ships urgency, routing, or toxicity wording on synthetic
   consensus alone.
2. **The conservative "non-toxic ≠ safe" framing is preserved everywhere.** No proposal
   weakens the never-certify-safe rule, and several strengthen it.

Drafted 2026-07-01 · Author: ideation pass over the working tree at commit `b05f870`
(branch `research-panel-and-roadmap`).
