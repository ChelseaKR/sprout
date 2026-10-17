# Case study: an evaluated, grounded RAG reference

What Sprout's committed evaluation evidence shows, what it does not, and one failure its own
harness missed.

*As of 2026-10-17. Every figure below is copied from a committed artifact, linked where it
appears; when an artifact is regenerated, it wins over this page.*

## What Sprout is

Sprout is a retrieval-augmented houseplant-care assistant that answers only from a
versioned, cited corpus, in English and Spanish. Its committed evaluation report is the
main thing it produces: the assistant exists so the harness has something honest to
measure. It is an independent, Apache-2.0 reference implementation, version 0.1.0 with no
tagged release. It runs offline by default and needs no account.

The design choices the evidence depends on:

- **Extractive generation with a citation guard.** The default generator copies sentences
  verbatim from retrieved passages, and an independent guard re-checks every sentence
  before it renders. Groundedness is therefore 100% by construction
  ([ADR-0003](adr/0003-extractive-generation-and-citation-guard-for-100pct-groundedness.md)).
- **It never says a plant is "safe."** A bilingual deny-list removes any sentence that
  certifies safety, and toxicity questions are routed to a vet or poison-control line
  ([ADR-0004](adr/0004-never-certify-safe-output-guard.md)).
- **Abstention.** Below a calibrated confidence threshold (0.25) the assistant refuses
  instead of guessing
  ([ADR-0012](adr/0012-recalibrated-abstention-thresholds-supersedes-0005.md)).
- **Deterministic offline stack.** A hashing embedder, BM25 and the extractive generator,
  seeded, so identical inputs produce byte-identical reports
  ([ADR-0001](adr/0001-offline-deterministic-generator-as-default.md)).

## What the committed evaluation shows

Source: [`audits/eval-report.md`](audits/eval-report.md). The judge is deterministic and
lexical, the target is the offline extractive pipeline, and there are 158 YAML cases across
9 suites.

| Suite | Score | Threshold | n | Reading |
|---|---|---|---|---|
| groundedness | 1.000 | ≥ 0.95 | 121 | Holds by construction. Sprout's citation guard verifies it, and Gauntlet (below) checks it independently. |
| safety | 1.000 | ≥ 0.95 | 42 | No "safe" certification, routing present, cites a source or refuses. |
| calibration (ECE) | 0.134 | ≤ 0.15 | 121 | Passes. Several reliability bins below 0.6 are marked FAIL in the report. |
| refusal | 0.923 | ≥ 0.90 | 39 | Meets the offline floor but not the 0.95 portfolio target. Three misses are listed in the report. |
| multilingual | 0.917 | ≥ 0.85 | 12 | 11 of 12 Spanish cases match their English anchor. `multilingual-snake-plant-overwater-es` fails. |
| language-parity (\|EN−ES\|) | 0.011 | ≤ 0.05 | 158 | EN 0.826 (n=121) vs ES 0.838 (n=37). The 95% CI on the gap is [0.000, 0.127]. |
| completeness | 1.000 | ≥ 0.90 | 3 | Under-powered. The 95% CI is [0.439, 1.000]. |
| conversation | 1.000 | ≥ 0.95 | 9 | Under-powered. |
| toxicity-coverage | 1.000 | ≥ 0.99 | 12 | Corpus-level check. |

A separate corpus-derived smoke suite passes 80 of 80 cases
([`audits/smoke-report.md`](audits/smoke-report.md)).

**Judge agreement.** The deterministic judge was checked against 66 human-labeled probes,
with raw agreement **0.955** and Cohen's **κ 0.906**. The floors are 0.80 and 0.60, and CI
fails below either one. All three disagreements are paraphrase-equivalence probes, which
is a lexical judge's known blind spot ([`audits/judge-calibration.md`](audits/judge-calibration.md)).

**Red team.** One structured manual exercise was run by the author on 2026-06-22. It
covered the OWASP Top 10 for LLM Applications (2025) categories that apply, in English and
Spanish, and found no open critical or high findings. A later erratum corrects a threshold
it misquoted ([`audits/red-team-2026-06-22.md`](audits/red-team-2026-06-22.md)).

**Governance artifacts.** These are self-assessed, not certified:

- An ISO/IEC 42001 Statement of Applicability lists 36 Annex A controls, 35 marked
  applicable and implemented and 1 not applicable, last regenerated on 2026-06-22. It
  states it is not a certification ([`audits/iso42001-soa.md`](audits/iso42001-soa.md)).
- The author's written EU AI Act classification places Sprout as a minimal-risk system
  with Article 50 transparency duties only. It is a decision record, not a legal opinion
  ([`audits/eu-ai-act-classification.md`](audits/eu-ai-act-classification.md)).

## A failure the harness missed, and what changed

Sprout is the reference target of [Gauntlet](https://github.com/ChelseaKR/gauntlet), a
separate evaluation harness by the same author that did not evolve alongside this
pipeline. Gauntlet's first per-case run found
[issue #168](https://github.com/ChelseaKR/sprout/issues/168): an English sentence rendered
inside a Spanish answer. Sprout's own suites had passed that answer. The cited-plant key is language-invariant by
design, and the language tag applies to the whole answer, so no check looked at the
language of each sentence. The manual red team's multilingual section had also reported
no finding.

The cause was retrieval that ignored language. A Spanish question naming a Latin binomial
also matched the English passage, and the extractive generator quoted it. Retrieval is now
scoped to the answer language, and the `multilingual` suite now checks the language of
each rendered sentence, so a mixed answer fails. The check is a small EN/ES function-word
heuristic with known false negatives, and it is pinned at zero false positives over the
bundled corpus. With the fix switched off, the suite drops to 0.833 and fails.

## Limits, stated plainly

- **The corpus is synthetic.** All 32 documents (16 species × EN/ES) are original CC0
  prose written for this project. Grounded means supported by a passage, not true. This is
  not veterinary advice ([data card](cards/data-card-corpus.md),
  [model card](cards/model-card.md)).
- **The Spanish evidence is thin.** There are 12 multilingual pairs and a 37-case Spanish
  slice. A 37-case slice can only rule out large EN/ES gaps: the interval above still
  allows one of up to 12.7 points.
- **The statistical gate is off.** Each result reports a Wilson interval and an
  under-powered flag, but the optional gate that would fail a suite whose lower bound
  misses its threshold is off by default and is not passed in CI. Turning it on today
  would fail `multilingual` on sample size alone
  ([`DEFINITION_OF_DONE.md`](https://github.com/ChelseaKR/sprout/blob/main/DEFINITION_OF_DONE.md)).
- **The committed run uses only the deterministic judge.** A model-based judge path
  exists behind a flag, but no committed report was produced with it.
- **The red team is manual and dated.** It is one exercise by the author, it predates
  #168, and it did not catch #168.
- **Accessibility review is partly automated.** The structural WCAG 2.2 AA, axe/pa11y and
  Lighthouse gates block merges. Manual screen-reader and keyboard walkthroughs are planned
  but have not been performed
  ([ACR](accessibility/ACR.md)).
- **The governance documents are self-assessments by the sole maintainer.**

Reproduce the numbers offline from a checkout with `make eval`. The
[README](https://github.com/ChelseaKR/sprout/blob/main/README.md) has the quickstart.
