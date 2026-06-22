# 0. Record architecture decisions

- Status: Accepted
- Date: 2026-06-22
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

Sprout's value is not the houseplant assistant; it is the *discipline* the assistant is
held to — retrieval-mandatory extractive generation, a never-certify-safe guard, calibrated
abstention, an offline-reproducible eval harness. Those are load-bearing decisions with
non-obvious tradeoffs, and several of them (the citation guard, the safety guard, the
abstention thresholds, the fail-closed eval loader) are flagged in the README as
"change only behind an ADR + CODEOWNERS review." That promise is empty without a place to
record the decisions and the reasoning that justified them.

The portfolio's `CODE-QUALITY-STANDARD` already names ADRs as the mechanism for recording
"language/version, layout, deps … review, ADRs," and treats a missing rationale as a
defect. A code comment explains *what*; an ADR preserves *why*, and *why not*, after the
context that produced the decision has evaporated.

## Decision

We record architecturally significant decisions as Markdown ADRs in `docs/adr/`, using a
lightweight **MADR**-style format: a title, a status line (with date and author), then
**Context**, **Decision**, and **Consequences** sections. We follow Michael Nygard's
original convention as adapted by MADR:

- Files are numbered sequentially and zero-padded: `NNNN-kebab-case-title.md`. This file is
  `0000`.
- Status is one of `Proposed`, `Accepted`, `Superseded by ADR-NNNN`, `Deprecated`. An
  accepted ADR is immutable; a reversal is a *new* ADR that supersedes it, not an edit.
- An ADR is required for any decision that changes a public contract, a hard rule, a
  guardrail (`guards.py`, `confidence.py`, the fail-closed eval loader), the retrieval or
  generation strategy, a dependency floor, or a security/accessibility posture.
- "Architecturally significant" excludes routine refactors, dependency bumps within the
  documented pin policy, and corpus data edits (corpus fixes are data, not code — see the
  spec's "Repairability" attribute).

## Consequences

- **Positive.** The "change only behind an ADR" guardrails in the README become
  enforceable: a reviewer can point at the absence of an ADR. New contributors learn the
  *why* without archaeology. Reversals are visible and dated rather than silent.
- **Positive.** ADRs are the audit trail that `RESPONSIBLE-TECH-FRAMEWORK` and
  `DOCUMENTATION-STANDARD` expect — decision provenance alongside the dated eval and
  accessibility artifacts.
- **Negative.** A small ongoing tax: each significant change carries a short writing cost,
  and the set must be kept honest (a superseded ADR that is silently edited defeats the
  purpose).
- **Neutral.** We deliberately use plain Markdown over a tool (`adr-tools`, Log4brains).
  The numbering and template are simple enough to maintain by hand, and a tool would add a
  dependency for no gate we need.

The remaining ADRs in this set (0001–0009) record the decisions that were already made and
embodied in the Phase 1–3 implementation; they are documented here so the rationale is not
lost.
