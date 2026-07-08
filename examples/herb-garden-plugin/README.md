# EXP-14 worked example: `sprout.eval` as a plugin-based package

This directory is a small, independently pip-installable package
(`sprout-herb-garden-example`) that proves two things about the `sprout.eval` harness
without changing a single line of the `sprout` package itself:

1. **The runner is corpus-agnostic.** [`corpus/`](corpus/) and [`config.yaml`](config.yaml)
   point the unmodified engine at a different care domain — culinary herbs (Basil, Mint,
   Rosemary), not houseplants — with the same manifest/provenance shape as the primary
   corpus (`corpus/manifest.yaml` at the repo root).
2. **A third party can add a suite with zero fork.** [`src/herb_garden_eval/suite.py`](src/herb_garden_eval/suite.py)
   defines `herb-actionable-advice`, a domain-specific check the built-in five suites
   don't cover, registered purely through the `sprout.eval.suites` entry point declared
   in [`pyproject.toml`](pyproject.toml):

   ```toml
   [project.entry-points."sprout.eval.suites"]
   herb-actionable-advice = "herb_garden_eval.suite:build_suite"
   ```

Once this package is installed alongside `sprout`, `sprout.eval.suite.resolve_suites`
(and `sprout eval --suites all`) discovers `herb-actionable-advice` automatically — see
`docs/adr/0013-frozen-plugin-api-for-sprout-eval.md` at the repo root for the design
rationale and the frozen public-API commitment this example is written against.

## What's here

- `corpus/` — three original, CC0-1.0 care documents (Basil, Mint, Rosemary) plus a
  manifest with the same required provenance fields (source, license, fetch date,
  language, topic) as the primary corpus.
- `config.yaml` — points `corpus.path`/`corpus.manifest` at this directory's corpus;
  every other setting keeps sprout's built-in default.
- `eval/herb-care.yaml` — seven authored cases (three groundedness, one refusal, three
  targeting the new plugin suite via `must_mention`).
- `src/herb_garden_eval/suite.py` — the plugin suite, written entirely against
  `sprout.eval`'s public, frozen surface (`from sprout.eval import EvalContext,
  ExampleOutcome, MetricDefinition, SuiteResult, aggregate`) — no internal imports.
- `run_example.py` — ingests the herb corpus, records the live offline engine over the
  cases, runs `groundedness`, `refusal`, `calibration`, and `herb-actionable-advice`, and
  writes the report to `report/`.
- `report/` — the committed output of the last real run of `run_example.py` (JSON,
  Markdown, HTML, JUnit, SARIF) — not fabricated, regenerate it yourself with the steps
  below to check it's byte-identical.

This example deliberately does not author `is_toxicity_query` or `pair_id`/`is_reference`
cases, so it does not run the built-in `safety` or `multilingual` suites — those would
(correctly) fail-closed on zero applicable items. It is a small worked proof, not a full
parity corpus; `run_example.py`'s `SUITE_SELECTOR` documents this choice.

## Running it

From the repo root, with `sprout`'s own dev environment active (`uv sync`), install this
example package too:

```sh
uv pip install -e examples/herb-garden-plugin
uv run python examples/herb-garden-plugin/run_example.py
```

This regenerates `report/eval-report.json` (and the other formats) offline, with no
network access and no changes to `sprout`'s own source. The run is byte-identical for
identical inputs, the same reproducibility property `make eval` relies on for the primary
corpus (ADR-0006).

To confirm the entry point is genuinely doing the discovery (rather than the suite having
been registered some other way), you can uninstall the plugin and see `resolve_suites`
report only the five built-ins:

```sh
uv pip uninstall sprout-herb-garden-example
uv run python -c "from sprout.eval.suite import available; print(available())"
```
