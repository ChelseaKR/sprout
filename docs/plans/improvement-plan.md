# Improvement plan: gates that could not fail

Audit date: 2026-08-28. Baseline: `main` at the tip of `origin/main`, working
tree clean, `make verify < /dev/null; echo "EXIT=$?"` -> `EXIT=0`, 838 tests,
94.52% coverage, every eval suite PASS.

The governing rule for this pass is that a check which cannot fail is worse
than no check. Everything below was measured against the tree.

## The findings, in order of what they cost

### 1. `.gitleaks.toml` disables every gitleaks rule

`.gitleaks.toml` at the repo root is:

```toml
[allowlist]
description = "Documented deterministic-token examples are not credentials."
paths = [ ... ]
```

gitleaks loads a `.gitleaks.toml` it finds as **the entire configuration**.
Without `[extend] useDefault = true` the default rule set is not included, so
this file leaves the scanner with an allowlist and **no rules at all**. Every
gitleaks run in this repository has been scanning with zero detectors and
reporting "no leaks found" because there was nothing it could find.

Measured, with a control. The same file containing a well-formed
`ghp_`-prefixed token, scanned two ways:

| Configuration in scope | Result | Exit |
|---|---|---|
| no `.gitleaks.toml` (gitleaks defaults) | `leaks found: 1` | 1 |
| this repository's `.gitleaks.toml` | `no leaks found` | 0 |
| `[extend] useDefault = true` prepended, allowlist unchanged | `leaks found: 1` | 1 |

This reaches every place gitleaks runs: `make security`, the
`gitleaks/gitleaks-action` job in `ci.yml` (the action reads the repository's
own config), and the `gitleaks` pre-commit hook.

Scanning the real repository with the defaults restored: **the full commit
history is clean, 0 findings**, so the fix does not turn CI red. A working-tree
(`--no-git`) scan reports 3, all the same known false positive the existing
allowlist was written for: a sentence in `providers/deterministic.py`
describing how the offline embedding works, which `generic-api-key` matches
because it contains the word token beside a quoted phrase. All three are
gitignored build artifacts that no gate scans: `site/` (mkdocs output) and a
`__pycache__/*.pyc`.

That sentence is deliberately paraphrased rather than quoted here. Quoting it
made this very document the first thing the repaired scanner found, which is
its own small proof that the repair works.

### 2. `make security`'s gitleaks line swallows a real finding

```make
	@command -v gitleaks >/dev/null 2>&1 && gitleaks detect --no-banner --redact || \
	  ( [ -n "$$CI" ] && echo "gitleaks not installed — failing (CI=true; ...)" && exit 1 || \
	    echo "gitleaks not installed locally — install it ...; CI enforces it regardless" )
```

`cmd && cmd2 || fallback` puts the fallback on *any* nonzero exit, and a
gitleaks that finds a secret exits 1. Run with a `gitleaks` on `PATH` that
reports a leak and exits 1:

```
WRN leaks found: 1
gitleaks not installed locally - install it; CI enforces it regardless
recipe exit code = 0
```

A real finding is reported by the tool, then announced as the tool being
absent, and the gate goes green. With `CI=true` the exit code is 1 but the
message still says "not installed", so the one case that fails, fails with the
wrong reason.

### 3. semgrep scans `src` and nothing else

`semgrep scan --config p/python --error src`, identically in `make security`
and in `ci.yml`'s `security` job. Measured from the run: **80 files scanned**.
The repository has **57 further Python files** under `tests/`, `scripts/` and
`eval/` that no SAST pass has ever read, including `scripts/export_web_bundle.py`
and `scripts/codeql_gate.py`, which are gate machinery.

### 4. Issue #107 is real, reproduces exactly, and is a safety-routing hole

Verified line by line and reproduced:

- 8 of the 16 `corpus/processed/*.es.md` files head their toxicity section
  `## Toxicidad`; the other 8 use `## Toxicity`. 7 of the 8 are on
  `ASPCA_TOXIC_PLANTS`, which holds 12 species.
- `chunk.py` slugifies the heading, so those chunks carry `topic="toxicidad"`.
- All four routing sites compare against the literal `"toxicity"`:
  `answer.py:293`, `answer.py:360`, `answer.ts:96`, `answer.ts:125`.

Reproduced against the committed corpus:

```
$ uv run sprout ask "¿Por qué mi Monstera causa irritación bucal y salivación excesiva?" \
    --language es --debug
La referencia citada incluye la Monstera (Monstera deliciosa) como tóxica para gatos y perros;
la ingestión puede causar irritación bucal, ...
--- trace ---
language=es safety=False injections=()
  [0.440] b16d69fb3595 monstera.es.md      # topic: toxicidad
```

`safety=False`, no vet or poison-control routing, no "no puedo certificar
ninguna planta como segura". The same fact reached through a keyword-classified
question renders the full escalation card. The mandatory escort disappears as a
function of the question's wording, in Spanish, for 7 of the 12 ASPCA-listed
toxic plants.

`propose.py` already carries
`SAFETY_TOPIC_SLUGS = frozenset({"toxicity", "toxicidad", "safety", "seguridad"})`
for exactly this hazard.

Nothing catches it: `toxicity.py::check_consistency` skips non-English docs,
`ToxicityCoverageSuite` inspects only the default language, and every case in
`eval/suites/safety.yaml` is authored with `is_toxicity_query: true`, so the
suite never exercises the path where content routes without a keyword.

### 5. Issue #108 is real and structural

Verified: `scripts/export_web_bundle.py` writes only `abstain_threshold` and
`low_confidence_threshold`; `web-static/src/config.ts`'s `ConfidenceConfig` has
no `fit` field; `web-static/src/confidence.ts` holds `MIDPOINT`/`STEEPNESS`/
`MARGIN_BONUS` as module constants and `scoreConfidence()` never reads config
for them. `confidence.py::_constants` does read `cfg.fit`.

`config/sprout.yaml` has no `confidence.fit` today, so nothing diverges yet.
The first time the documented `sprout fit-confidence` workflow is used and its
output committed, the browser at `sprout.chelseakr.com` computes a different
confidence, and therefore different abstain and low-confidence decisions, than
the CLI for the same question. `sprout eval` does fail closed on a stale fit
(`cli.py:357`), which confirms a committed fit is the expected steady state.

### 6. The Makefile defines `corpus-report` twice

```
Makefile:81: warning: overriding commands for target `corpus-report'
Makefile:65: warning: ignoring old commands for target `corpus-report'
```

The surviving recipe drops `--config $(CONFIG)`, so `make verify CONFIG=...`
silently runs that one gate against the default config. `make` prints the
warning on every invocation, including inside `make verify`.

## Named traps checked and found already handled

Recorded so a later reader knows the ground was covered.

- `uv sync --frozen` is not used as a gate. CI uses `uv sync --locked`.
- `semgrep test` does not appear; the scope problem is #3, not an empty suite.
- `scripts/codeql_gate.py` fails, loudly and with the reasoning written out,
  when it finds zero SARIF files. It is the model the rest of this plan follows.
- `slos/` and `alerts/` could each be empty without `sprout slo-check`
  objecting, which is documented as Tier A's absence rather than a schema
  error; `tests/test_slo.py` asserts the committed files exist and are valid,
  so the corpus-size guard is present, just at the test layer.
- ruff and mypy cover `src` and `tests`; mypy's `files` reaches the gate
  scripts.
- `sprout ci-parity-check` mechanically diffs `make verify` against the
  required CI jobs, which is the "CI stage with no make target" trap already
  closed. It does not, and cannot, tell whether the commands it matches are
  themselves correct, which is what #1 to #3 are.
- No `for` loop takes its status from its last iteration; `ci.yml`'s one loop
  (line 306) accumulates and fails on any bad result.
- The only `cmd && cmd2 || fallback` in the repository is #2.

## Phases

Each phase is a commit, with a test that fails before and passes after, and
every new guard is broken deliberately before it is trusted.

1. **`[extend] useDefault = true`** in `.gitleaks.toml`, with a test that plants
   a synthetic token under `tmp_path`, runs gitleaks with the committed config,
   and asserts it is found. Skipped, never passed, when gitleaks is absent.
2. **The `make security` recipe stops swallowing findings**: install-check and
   scan become separate statements, so a nonzero scan fails the target and a
   missing tool says so in its own words. A test asserts the recipe's shape.
3. **semgrep reaches every Python file**, in the Makefile and in `ci.yml`
   together, with a test that fails if the two diverge or if a Python source
   root is left out.
4. **Issue #107**: `answer.py` and `answer.ts` route off a shared bilingual slug
   set rather than the literal `"toxicity"`, with the Spanish reproduction as a
   test and the English behaviour pinned so the fix cannot pass by routing
   everything.
5. **Issue #108**: the export carries `confidence.fit`, the TS config declares
   it, `scoreConfidence` reads it with the current constants as the fallback,
   and a parity test asserts the exported bundle agrees with the Python config.
6. **One `corpus-report` target**, keeping `--config $(CONFIG)`.

## Not done here, and why

- PR #55 (coverage-vs-risk curve) is in-flight owner work on `confidence.py`,
  which is CODEOWNERS-guarded. Nothing here touches `confidence.py`.
- PRs #113 and #114 are Dependabot bumps.
- The three working-tree gitleaks findings in `site/` and `__pycache__/` are
  build artifacts in gitignored paths that no gate scans. Widening the
  allowlist to cover them would re-introduce exactly the class of hole this
  plan closes, so they are named here and left alone.
