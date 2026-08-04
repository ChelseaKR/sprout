# A worked corpus proposal (research item E5)

[`docs/RESEARCH-ROADMAP.md`](../../docs/RESEARCH-ROADMAP.md) E5 asks for "a low-/no-code
'propose a cited passage + an eval case' path with provenance fields (source, license,
fetch_date, lang, topic) enforced and a representational-harm checklist". This directory is
the worked example that path is tested against, in the same spirit as
[`examples/herb-garden-plugin/`](../herb-garden-plugin/) for the eval plugin API.

The corpus is the bottleneck every persona in [`docs/USER-RESEARCH.md`](../../docs/USER-RESEARCH.md)
runs into, and unsourced plant-care text is exactly what goes wrong in this domain (EV1,
EV4). So contribution is not a free-text form: a proposal is reviewed mechanically before a
human spends attention on it.

## Two doors, one schema

**No code.** Open a [corpus proposal issue](../../.github/ISSUE_TEMPLATE/corpus_proposal.yml);
its fields map one-to-one onto the YAML below, and a maintainer converts it.

**YAML.** Start from the template, fill it in, and review it locally — all offline:

```bash
uv run sprout propose template > proposals/my-plant.yaml
uv run sprout propose check proposals/my-plant.yaml
```

## What the review checks

`sprout propose check` (`src/sprout/propose.py`) is a pure function of the proposal, the
corpus already on disk, and the date. It reuses the maintainer-side corpus workbench
(EXP-12, `src/sprout/corpus_report.py`) rather than re-implementing its rules, so a
contribution is held to exactly the standard the shipped corpus is held to:

| Area | Enforced |
|---|---|
| Identity | slugified species, not already in the corpus, botanical name present |
| Provenance | license on the contribution allowlist, http(s) URL, synthetic prose confined to the `example.invalid` placeholder host, non-synthetic content gated on an expert sign-off |
| Dates | ISO-8601, never in the future; E7's citation-freshness SLA (stale is a *warning*, unusable is an error) |
| Languages | every `languages.supported` language proposed together; EN/ES section-count parity; no heading left untranslated |
| Topics | the reference-language passage covers the corpus's canonical topic taxonomy |
| Chunk quality | no sentence longer than `chunk.max_words`; the "names its plant" extraction-safety heuristic |
| Safety | every proposed sentence run through the shipped never-certify-"safe" guard (`guards.asserts_safety`) — a certification cannot enter the corpus any more than it can leave through the answer path |
| Representational harm | every checklist box affirmed and attributed; the medicinal/edibility box cross-checked against an EN/ES claim vocabulary |
| Eval case | loads as a `DatasetItem`, id not already taken, cites one of the proposed documents, and every `expected_fact` appears verbatim in the passage |

## The three statuses

- **`changes-requested`** — at least one error. Not mergeable as authored.
- **`ready-for-expert-review`** — mechanically clean, but safety-bearing (toxicity or
  ingestion prose, or a toxicity eval case) with no committed sign-off. This tool cannot
  stand in for the licensed veterinary toxicologist / poison-control clinician — or, for
  Spanish copy, the native horticulture reviewer — that
  [`docs/RESEARCH-ROADMAP.md`](../../docs/RESEARCH-ROADMAP.md) requires, and it does not
  pretend to. Recording the gate as a machine-checked state is the point.
- **`ready-to-merge`** — mechanically clean and either not safety-bearing or carrying an
  `expert_review` block whose sign-off artifact is committed.

`propose check` exits non-zero only on `changes-requested`, so the merge-blocking CI step
(`propose-check`, inside the `eval-a11y` job and `make verify`) catches real defects without
manufacturing a clinician's approval. `--require-expert-review` tightens it for a maintainer
about to merge.

## This example

[`parlor-palm.yaml`](parlor-palm.yaml) proposes *Chamaedorea elegans* with EN + ES passages
across all five corpus topics, a groundedness case pinned to the watering passage, and a
completed harm checklist. It reviews with **zero findings** and lands on
`ready-for-expert-review` — the honest end state, because it carries toxicity prose. Nothing
here is merged into `corpus/`: a proposal is reviewed, not auto-applied.
