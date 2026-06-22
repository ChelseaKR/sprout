<!-- Conventional-commit title, e.g. feat(eval): add reliability-diagram segments -->

## What & why

## Definition of done
- [ ] `make verify` is green locally (lint · type · test ≥90% · security · eval · a11y)
- [ ] Tests added/updated; acceptance criteria linked to an issue
- [ ] If a guardrail changed (`guards.py`, `confidence.py`, `eval/`), an ADR is linked and a CODEOWNER reviewed
- [ ] Docs / CHANGELOG updated; ISO 25010 quality characteristic named
- [ ] Eval report regenerated if behavior changed; no baseline regression
- [ ] Rollback plan noted (config flag or revert)

## ISO 25010 characteristic(s) this PR touches

## Rollback plan
