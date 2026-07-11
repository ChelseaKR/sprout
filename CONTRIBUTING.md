# Contributing to Sprout

Thanks for your interest. Sprout is an independent personal open-source project (Apache-2.0,
unaffiliated with any employer or client). It is a *reference implementation*: the bar is high
on purpose, because the whole point of the repo is to demonstrate responsible-AI rigor that is
mechanically enforced rather than asserted.

This file covers only what is specific to Sprout. The cross-cutting rigor — coverage floors,
the merge-gate model, the security posture, the release pipeline — lives **once** in the
portfolio [`STANDARDS/`](../STANDARDS/README.md) and is referenced here, not restated. When a
target moves (an OWASP/WCAG/ISO revision), it moves there.

## The one command that proves it: `make verify`

```bash
make install        # uv sync (venv + dev deps)
make verify         # the full local mirror of the CI gate set
```

`make verify` runs, in order, `lint · type · test (≥90%) · security · eval · a11y · docs ·
workflow-lint · ci-parity-check` — the same tools, configs, and thresholds the CI-required checks
enforce (`CI-CD-STANDARD.md` §`make verify` parity): CI invokes the equivalent commands directly
inside `test`/`security`/`eval-a11y`/`docs`/`zizmor` jobs rather than shelling out to `make`, so
this is tool-for-tool parity, not literally one CI step running `make verify`. A change is not
done until `make verify` is green locally. There is a single required `ci-gate` check and no admin
bypass on `main`. (As of 2026-07-05 the `security` target's `pip-audit` and `semgrep` steps are
unconditionally blocking, matching the CI `security` job exactly; only `gitleaks` remains locally
best-effort when the binary isn't installed, hard-failing if `CI=true` is set and it's still
missing — see `Makefile` §`security`.)

The parity claim above is no longer just prose: `make ci-parity-check` (`sprout ci-parity-check`,
implemented in `src/sprout/ci_parity.py`) mechanically diffs `.github/workflows/ci.yml`'s required
jobs against the `Makefile` targets that are supposed to mirror them and fails on any unexplained
one-sided command. It runs as part of `make verify` and as its own `ci-parity` job in CI (a
dependency of `ci-gate`), so drift between the two is caught the moment it's introduced instead of
relying on a human noticing.

Useful individual targets: `make fmt`, `make lint`, `make type`, `make test`, `make eval`,
`make eval-baseline`, `make a11y`, `make docs`, `make demo`. Run `make help` for the full list.

## Branch model

```
claude/<topic>   ──▶   develop   ──▶   main
 (work branches)      (integration)   (released, tag-protected)
```

- **`main`** is the released, protected branch. Tags (`vX.Y.Z`) are cut only here, only after every
  gate is green (see [`RELEASE-AND-VERSIONING-STANDARD.md`](../STANDARDS/RELEASE-AND-VERSIONING-STANDARD.md)).
- **`develop`** is the integration branch. PRs target `develop`.
- **`claude/<topic>`** is a short-lived work branch (one logical change). Name it for the change,
  e.g. `claude/calibration-reliability-segments`. Open a PR into `develop`; never push to
  `main` or `develop` directly.

A release promotes `develop` → `main` once the eval report and audits are regenerated and committed.

## Commit messages — Conventional Commits

Every commit and every PR title follows [Conventional Commits 1.0.0](https://www.conventionalcommits.org/):

```
<type>(<scope>): <imperative summary>

<body — what & why, not how>

Signed-off-by: Your Name <you@example.com>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`, `perf`, `revert`.
Common scopes: `eval`, `retrieve`, `guards`, `confidence`, `corpus`, `web`, `a11y`, `i18n`, `infra`.
A `!` after the scope (or a `BREAKING CHANGE:` footer) marks a breaking change to the public API
and forces a `MAJOR` bump. Conventional Commits drafts the CHANGELOG, but a human curates the
released section — a commit dump is not a changelog.

## DCO sign-off (required)

Contributions are accepted under the [Developer Certificate of Origin 1.1](https://developercertificate.org/).
Sign off every commit so the certification is on record:

```bash
git commit -s -m "feat(eval): add Spanish-mirror parity case set"
```

`-s` appends the `Signed-off-by:` trailer matching your `git config user.name`/`user.email`.
An unsigned commit fails CI. If you forgot, `git commit --amend -s` (or
`git rebase --signoff develop` for a series) fixes it. By signing off you certify you wrote the
contribution or have the right to submit it under the project's Apache-2.0 license.

## Pull requests — Definition of Done

The PR template ([`/.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)) and
[`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md) are the contract. Before requesting review:

- [ ] `make verify` is green locally (lint · type · test ≥90% · security · eval · a11y).
- [ ] Tests added or updated; acceptance criteria trace to an issue.
- [ ] Docs and `CHANGELOG.md` `[Unreleased]` updated; the **ISO 25010 quality characteristic**
      the change touches is named.
- [ ] If a *guardrail* changed — `src/sprout/guards.py` (citation + never-certify-safe),
      `src/sprout/confidence.py` (abstention thresholds), or `src/sprout/eval/dataset.py`
      (fail-closed loader) — an **ADR** is linked and a CODEOWNER reviewed it. These are
      load-bearing safety code; they do not change casually.
- [ ] The eval report is regenerated if behavior changed (`make eval`) and there is **no baseline
      regression** against `docs/audits/eval-baseline.json`. Intentional baseline movement is its
      own commit with `make eval-baseline` and a rationale.
- [ ] A **rollback plan** is noted (a config flag in `config/sprout.yaml`, or a clean revert).

Solo-maintainer note ([`CODE-QUALITY-STANDARD.md`](../STANDARDS/CODE-QUALITY-STANDARD.md)): the
"≥1 review" gate is satisfied by an explicit, recorded self-review pass *plus* every AUTO-GATE
green. The point is that the checks ran and were acknowledged, not headcount.

## What lives where (so you change the right file)

- **Horticultural facts** are *data*, not code: fix them in `corpus/` and re-`make ingest`. A wrong
  answer is usually a corpus or eval-case defect, not a Python bug.
- **New eval cases** go in `eval/suites/` as YAML (id, question, expected behavior, required
  citation/fact, language tag, rationale). Adding a hard case that currently fails is welcome —
  failures are shown, not hidden.
- **New providers** go behind the adapter in `src/sprout/providers/`; **new eval suites** wire in
  without touching the runner. Keep `ingest · retrieve · generate · guard · eval` independent.
- **Offline determinism is non-negotiable.** The default path (HashingEmbedding + BM25 +
  ExtractiveGenerator) must stay network-free and seeded so reports are byte-identical for
  identical inputs. Anything needing a cloud account belongs behind a config switch and the
  Bedrock/Anthropic provider seam, and must not be required for `make verify`.

## Security issues

Do **not** open a public issue for a vulnerability. Follow [`SECURITY.md`](SECURITY.md) for private,
coordinated disclosure.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating you agree to
uphold it.

---

*Maintainer: Chelsea Kelly-Reif · License: Apache-2.0 · This is not veterinary or medical advice.*
