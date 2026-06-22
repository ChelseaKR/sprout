# 9. Judge model differs from the answer model

- Status: Accepted
- Date: 2026-06-22
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

The eval harness (ADR-0006) blends deterministic checks with an **LLM-as-judge** for the
properties no string match can settle — groundedness (does the claim follow from the
sources?) and helpfulness. The integrity of that judgment is the integrity of the headline
artifact. The well-documented failure mode is **self-preference / self-evaluation bias**: a
model grading its own outputs systematically scores them higher, because the same training
distribution that produced the answer also recognises and favours its own style. A judge
that *is* the answer model launders the assistant's own blind spots into a passing grade.

`AI-EVALUATION-STANDARD` standardizes on Anthropic Claude for both generation and
LLM-as-judge, and requires the judge configuration to be committed and versioned, with a
reported human-agreement sample (Cohen's κ). It does not let the judge be the answer model.
The spec states the rule directly: "the judge model differs from the answer model."

## Decision

The judge model is **structurally distinct** from the answer model, and the distinction is
pinned in versioned config (`eval/llm_judge.py`, `eval/judge.py`).

- **Answer model:** when the cloud seam is enabled, **Claude Haiku** (`build_generator`
  default `claude-haiku-4-5-...`).
- **Judge model:** **Claude Sonnet** (`DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"`) — a
  different, stronger model, deliberately not Haiku.
- **One model-touching seam.** A suite consults the model only through the `Judge` Protocol
  (`entails` / `contains` / `equivalent`), so a suite is identical whether it runs under the
  offline `DeterministicJudge` (lexical coverage + a negation-polarity contradiction guard,
  fully reproducible, no network) or the `AnthropicJudge`. The model call is injected as a
  `CompletionFn`, so the judge is testable offline and is never hit in CI.
- **Hashed judge identity.** Judge method, model id, prompt version, temperature (0.0),
  max-tokens, and thresholds live in one hashed `config`; the `config_hash` is folded into
  the run `RunFingerprint`. Any change to the judge — model, prompt, or threshold — changes
  the run identity and invalidates a calibration record (ADR-0005).
- **Fail-closed parsing.** Malformed judge output raises (`_parse_score`), never silently
  passes.
- **Human-agreement check.** A 10% human-agreement sample with Cohen's κ is reported, so
  the judge itself is audited, not trusted.

## Consequences

- **Positive.** Self-preference bias is structurally excluded: the grader is never the
  gradee. Groundedness/helpfulness scores are independent of the answer model's own taste.
- **Positive.** The default offline path uses the `DeterministicJudge`, so the entire eval —
  including the judged suites' deterministic analogue — runs reproducibly with no network or
  key; the LLM judge is an opt-in upgrade, not a CI dependency.
- **Positive.** Folding the judge config hash into the run fingerprint means a judge change
  can never silently move scores — it is visible in the run identity and invalidates stale
  calibration.
- **Negative — the honest limit.** Different-model is necessary but not *sufficient* to kill
  judge bias; Claude judging Claude shares a vendor and training lineage, so family-level
  bias can remain. The κ human-agreement sample is the mitigation that keeps the judge
  honest, and the model card states the residual risk.
- **Neutral.** Pinning specific model ids means the pins must be maintained as models are
  deprecated; the bump path is documented and each bump changes the run fingerprint, which
  is the intended, visible behavior.
