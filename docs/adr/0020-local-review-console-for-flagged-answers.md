# 20. A local, opt-in review console for flagged/refused answers (EXP-17)

- Status: Accepted
- Date: 2026-07-08
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

`Answer.low_confidence` (`confidence.py`) already flags an answer "for human review," and
`Answer.refused` marks an honest abstention — but no review surface existed. Both signals were
computed and then dropped on the floor. Three assets that currently starve for human
judgments — the judge probe set (`eval/judge_probes.yaml`, gated on a 30-day freshness check),
FIX-08's confidence re-fit, and new eval cases — all improve from the same stream of reviewed
traffic the runtime already identifies as valuable.

Building this well means capturing question text, which is data the rest of Sprout deliberately
never persists: `obs.py`'s `Logger` only ever writes a closed field whitelist, and the README's
hard rules lean on "no user-query persistence in the demo." A review console is worth building
only if it does not quietly weaken that posture.

## Decision

The review console is **local-first, opt-in, and off by default** (`review.py`,
`config.py::ReviewConfig`), following the same discipline already applied to the photo-ID
(ADR-0010) and reminders (ADR-0011) opt-in seams:

1. **A separate, user-consented capture file — not the PII-free operational log.**
   `ReviewQueue` is one JSON file on the maintainer's own machine (`var/review/queue.json` by
   default), written only when `ReviewConfig.enabled` is set `true` in `config/sprout.yaml`.
   Nothing is written until a maintainer opts in, and the CLI (`_maybe_capture_review` in
   `cli.py`) is the only thing that decides *whether* to call `ReviewQueue.capture` —
   `capture` itself does not consult config, so it can never silently start capturing on its
   own if a caller forgets the gate.
2. **Capture is narrow: only what is already flagged.** A trace is queued only when
   `Answer.low_confidence` or `Answer.refused` is true (each independently toggleable via
   `capture_on_low_confidence` / `capture_on_refusal`), never on every question.
3. **`sprout review` is the labeling workflow.** `queue` / `show` list and inspect captured
   items; `label` (or the interactive `run` walk-through, which is also what bare `sprout
   review` launches) assigns one of `{correct, incomplete, wrong-plant,
   should-have-refused}`.
4. **Three exporters, none of which write to a committed, authoritative file directly.**
   `export_judge_probes`, `export_confidence_fit_cases`, and `export_eval_case_drafts` turn
   labeled items into `JudgeProbe`- and `DatasetItem`-shaped YAML under `var/review/` for a
   maintainer to review and hand-merge into `eval/judge_probes.yaml` / `eval/suites/*.yaml`.
   Label quality is one person's judgment; provenance says so explicitly
   (`source: local-review-queue`), and nothing here silently starts backing a merge-blocking
   gate the way a corpus-derived case would.
5. **Deterministic and clock-injectable**, mirroring `ReminderStore`: item ids are a
   content+position hash, `capture`/`label` are unit-testable offline (`test_review.py`).
   At `max_items` capacity, the oldest item is dropped rather than raising — capture is
   best-effort background instrumentation and must never break the caller's request.
6. **DPIA delta committed with the feature, not after.** `docs/RESPONSIBLE-TECH-AUDITS.md`
   §C gains a data-inventory row and a bullet for the review queue, in the same PR that ships
   the code — the same "audit-before/with-feature" discipline EXP-17's own shape calls for.

## Consequences

- **Positive.** The maintainer-side complement to E5's SME contribution path: real reviewed
  traffic, not hand-authored probes, can refresh the judge probe set and the confidence fit
  each release, per the ROADMAP's judge-calibration-freshness row.
- **Positive.** Privacy is the default, not a mode: with `review.enabled: false` (the
  shipped default), the CLI's behavior is bit-for-bit what it was before this ADR — no new
  file, no new state, no behavior change at all.
- **Negative — the honest limit.** This is single-maintainer labeling, not a panel: the κ
  gate still compares judge to *human*, now with more `n`, but provenance on every exported
  probe/case marks it as a single reviewer's judgment, not a substitute for the diverse
  human-agreement sample the calibration record already reports separately.
- **Negative.** `serve` (the optional server) is not wired to capture in this pass — only the
  `ask` CLI path is. Wiring `serve` would mean calling `Assistant.trace()` (which recomputes
  retrieval+generation) on every flagged/refused request in a latency-budgeted path; that
  trade-off deserves its own look rather than riding in on this ADR. `ReviewQueue.capture`
  is already generic over any `AnswerTrace`, so wiring it into `server.py` later is additive,
  not a redesign.
- **Neutral.** The queue path is config-driven, so an adopter can relocate or sandbox it, same
  as reminders.

## See also

- `docs/ideation/03-expansions.md` EXP-17 — the design rationale this implements.
- ADR-0010 (photo-ID as a selector, not a fact source) and ADR-0011 (local-first reminders) —
  the opt-in, local-only precedent this ADR follows.
- `docs/RESPONSIBLE-TECH-AUDITS.md` §C — the DPIA delta for this feature.
