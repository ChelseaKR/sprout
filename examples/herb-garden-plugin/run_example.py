#!/usr/bin/env python3
"""Run the EXP-14 worked example end to end: ingest the herb-garden corpus, record the
live (offline, deterministic) engine over the authored cases, run the eval suites
(including the ``herb-actionable-advice`` plugin discovered via the ``sprout.eval.suites``
entry point), and write the report next to this script.

Everything here is written against sprout's public API — ``sprout.config``,
``sprout.answer.Assistant``, and the frozen ``sprout.eval`` surface (ADR-0013). No sprout
internals are imported. See README.md for how to run this.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sprout.answer import Assistant
from sprout.config import load_config
from sprout.eval import (
    load_entry_point_suites,
    load_suite_dir,
    resolve_suites,
    run_evaluation,
    write_sidecar,
)
from sprout.eval.judge import DeterministicJudge
from sprout.eval.record import record
from sprout.eval.report import render_markdown, write_reports
from sprout.ingest import ingest

HERE = Path(__file__).resolve().parent
# sprout.config's corpus/store paths are resolved relative to the process cwd (the same
# way `make eval` relies on being run from the repo root) — chdir here so this script
# behaves identically no matter where it's invoked from, and so it reads *this* example's
# corpus/config rather than whatever corpus/ happens to sit under the caller's cwd.
os.chdir(HERE)
CONFIG_PATH = Path("config.yaml")
SUITE_DIR = Path("eval")
SIDECAR_PATH = Path("eval") / "suites.sha256"
OUT_DIR = Path("report")

# This example intentionally authors only the fields the four suites below need
# (groundedness/refusal from questions+facts, calibration from the engine's own recorded
# confidence, herb-actionable-advice from `must_mention`). It does not author
# `is_toxicity_query` or `pair_id`/`is_reference` cases, so the built-in `safety` and
# `multilingual` suites would (correctly) fail-closed on zero applicable items — this is
# a deliberately small worked example, not a full parity corpus.
SUITE_SELECTOR = "groundedness,refusal,calibration,herb-actionable-advice"


def main() -> int:
    plugin_suites = load_entry_point_suites()
    if "herb-actionable-advice" not in plugin_suites:
        print(
            "warning: the herb-actionable-advice plugin was not (re)discovered this run "
            "— install this package first: `uv pip install -e .` (or `pip install -e .`) "
            "from examples/herb-garden-plugin/",
            file=sys.stderr,
        )

    cfg = load_config(CONFIG_PATH)
    store = ingest(cfg)
    assistant = Assistant.from_store(cfg, store)

    dataset = load_suite_dir(SUITE_DIR, verify_hash=False)
    write_sidecar(dataset, SIDECAR_PATH)  # regenerate the pin, mirroring `--update-baseline`
    golden = record(assistant, dataset, cfg)

    result = run_evaluation(
        golden,
        DeterministicJudge(),
        resolve_suites(SUITE_SELECTOR),
        target="deterministic:extractive",
    )

    OUT_DIR.mkdir(exist_ok=True)
    write_reports(result, str(OUT_DIR))
    print(render_markdown(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
