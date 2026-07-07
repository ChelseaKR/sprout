# Impact × effort, dependencies, and sequencing (drafted 2026-07-01)

Covers all IDs from [`02-large-scale-fixes.md`](02-large-scale-fixes.md) and
[`03-expansions.md`](03-expansions.md). This sequence is **additive to** — and assumes —
the RESEARCH-ROADMAP's own Now/Next/Soon (R1/R2/R3 first, then the P1 safety-loudness
and proof items). Nothing here re-sequences those; it slots the net-new work around
them.

## Impact × effort matrix

Impact = expected effect on Sprout's core promises (safety correctness, claim
credibility, reproducibility, reach). Effort tiers from the item definitions.

| | **S** | **M** | **L** | **XL** |
|---|---|---|---|---|
| **Very high impact** | FIX-11 | FIX-01 · FIX-04 · FIX-06 | FIX-02 · FIX-13* | EXP-08 · EXP-09* |
| **High impact** | EXP-10 | FIX-03 · FIX-05 · FIX-07 · FIX-08 · FIX-12* · EXP-13 | FIX-09 · FIX-10 · EXP-03 · EXP-04 · EXP-07 | EXP-11* · EXP-15 · EXP-16 |
| **Medium impact** | — | EXP-01 · EXP-02 · EXP-05 · EXP-06 · EXP-12 · EXP-17* | EXP-14 | — |

`*` = calendar dominated by a human/SME/real-data gate, not by engineering effort
(see the gates section below). FIX-13 is S–M in code but sits in the very-high row
because a child-ingestion query currently receives an animal-poison-control card.

**Best value-per-effort cluster:** FIX-01 + FIX-02 + FIX-06 + FIX-11 — the
"self-claims integrity" block. It requires no SME, no new architecture, and directly
protects the repo's differentiating asset (trustworthy paperwork). FIX-04 joins it as
the highest-leverage pure-code safety improvement (the committed report's own
`safety-025` failure).

## Dependency notes

- **FIX-01 ← decisions**: the reconciliation pass must *choose* canonical values
  (0.25/0.50, AA, refusal 0.90-offline/0.95-cloud) before the linter can enforce them.
- **FIX-02 ← FIX-12**: enabling the Wilson statistical gate before the multilingual
  suite reaches n ≥ 30 flips CI red on power, not quality. Wire the other six items
  first; flip the gate with FIX-12.
- **FIX-12 ← native-Spanish reviewer** (gate) for new ES safety-adjacent case text.
- **FIX-13, FIX-03 (copy), EXP-09 ← SME gates** (below). Code can be staged behind
  flags; nothing user-visible ships un-reviewed.
- **FIX-08 ← FIX-07 / EXP-03**: any retrieval change invalidates the confidence fit;
  build the re-fit tool before or alongside retrieval changes, and re-run it after.
- **FIX-09 → EXP-06, EXP-08, FIX-13**: locale bundles should land before new
  user-facing strings multiply (bands, static build, card variants), or the scatter
  FIX-09 removes grows back.
- **FIX-11 → EXP-07**: remove the phantom `session_memory` first; multi-turn
  re-introduces session state deliberately, with its own DPIA row.
- **FIX-02 → EXP-13**: the trend ledger extends the (newly wired) baseline diff.
- **EXP-14 → EXP-15/EXP-16**: a frozen public API and proven plugin seam are
  prerequisites for the registry and the library extraction. EXP-16 additionally gates
  on a real second consumer (Family Greenhouse Phase A per CLAUDE.md's phasing).
- **FIX-10 ↔ R4**: server hardening ships with, not after, the public deployment.
- **EXP-03/EXP-04** are ADR-gated by house rule (eval delta required) and touch
  CODEOWNERS-guarded files, as do FIX-05's normalization changes and FIX-08.

## Suggested sequence (beyond the existing roadmaps)

**Now — make the self-claims true (no SME required, unblocks everything).**
FIX-01, FIX-02 (six of seven items; statistical gate deferred), FIX-06, FIX-11,
FIX-04, FIX-05. Outcome: every AUTO row enforced or honestly relabeled; the four
numeric drifts gone; the packaged corpus provably in sync; routing gaps that need no
new copy closed; the guards fuzz-tested. This block is the credibility floor for
everything later.

**Next — power, scale, and gated safety work in flight.**
FIX-12 (author EN sizing now; ES text queued for the reviewer) → flip the statistical
gate (completing FIX-02); FIX-07 + FIX-08 (retrieval scale + re-fit tooling, paired);
FIX-03 (species gate; refusal copy queued for review); **start the SME loop for FIX-13
and EXP-09 immediately** — recruitment is the long pole, and it is the same outreach the
RESEARCH-ROADMAP already requires for R1; EXP-13 (trend ledger); EXP-10 (ICS export);
EXP-12 (corpus workbench, ahead of the R1 corpus landing so growth arrives with QA in
place).

**Later — capability expansions on the hardened base.**
FIX-09 (locale bundles) then EXP-06; EXP-01 + EXP-02 (answer quality, validated with
real users per the walk-risk); EXP-05; FIX-10 with the R4 deployment; EXP-03 then
EXP-04 (each behind an ADR with a measured eval delta); EXP-07 (multi-turn, with its
DPIA); EXP-17 (review console, with its DPIA); EXP-14 (plugin API + second-domain
proof).

**Horizon bets — pursue at most one at a time.**
EXP-08 (Sprout Static) is the highest-leverage bet if reach and privacy story dominate;
EXP-09 → EXP-15 (structured toxicity → signed registry) if the safety-data mission
dominates; EXP-16 (groundedkit) only when Family Greenhouse Phase A creates the second
consumer; EXP-11 (on-device photo-ID) only after its training-data licensing and
accuracy-measurement story is solid.

## Items requiring human / SME / real-data gates (explicitly separated)

The following do **not ship** on maintainer judgment or synthetic consensus alone,
consistent with the RESEARCH-ROADMAP's "validate with real users / risks" section. A
veterinary-toxicologist (or, where noted, poison-control clinician / medical
toxicologist) review is required before shipping **any safety copy**, and the
conservative **"non-toxic ≠ safe" framing is preserved in every one of these items —
none may weaken it, and several exist to extend it.**

| Item | Gate | What specifically is gated |
|---|---|---|
| FIX-13 exposure-split escalation card | **Poison-control clinician / medical toxicologist**, plus ES human review | The human-poison-control numbers, both languages' wording, and whether to show both cards on ambiguous queries. Code can merge dark; copy renders only after a dated, committed sign-off. |
| EXP-09 structured toxicity table | **Veterinary toxicologist** | Schema semantics (severity classes), every real data row, and the rendering rules — especially that "not listed as toxic" rows always carry the non-toxic ≠ safe caveat. Synthetic rows only until then (same posture as the existing corpus). |
| FIX-03 species-gate refusal copy | **Vet toxicologist review of the refusal message**; gazetteer species list reviewed for correctness | The localized "species not covered" message on toxicity queries is safety copy by this repo's definition. |
| FIX-04 keyword expansion | Light-touch SME check | Mechanical vocabulary lists, but an SME should confirm no animal class is mis-prioritized; existing reviewed copy is unchanged. |
| FIX-12 / any new ES case or string | **Native-Spanish horticulture reviewer** | Per RESEARCH-ROADMAP: no ES safety-adjacent text on automated parity alone. |
| EXP-11 on-device photo-ID | **Real data**: licensed training images + held-out accuracy measurement | No default-on until the per-species confusion matrix is published; accuracy claims are measurements, not estimates. |
| EXP-01/EXP-02 answer-shape changes | **Real-user validation** | A1's adopt/walk risk: verify beginners read multi-facet and "sources differ" answers as more trustworthy, not more confusing. |
| EXP-15 third-party corpora | **Per-publisher review policy** (design-level SME input) | Unreviewed publishers' toxicity content renders with a provenance banner and can never alter Sprout's own routing/deny-list strings. |
| EXP-17 trace capture | **DPIA before code** | Stores question text locally; off by default, own inventory row, documented retention. |
| R1 real toxicity corpus (existing item, restated for completeness) | **Veterinary toxicologist** | Unchanged from RESEARCH-ROADMAP; the FIX-13/EXP-09 outreach is the same recruitment effort — scope one engagement to cover all three review streams. |

**Standing invariant for every item in this folder:** the never-certify-safe rule
(`guards.asserts_safety` / `safety_filter`), the mandatory vet/poison-control routing,
and the "non-toxic ≠ safe" disclosure are floors, not variables. Any proposal found to
require weakening them is rejected as specced, not negotiated.
