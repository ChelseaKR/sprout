"""What the browser computes must be what the CLI computes.

The static site at sprout.chelseakr.com runs a TypeScript port of the same pipeline,
driven by `public/data/config.json` which `scripts/export_web_bundle.py` writes from
`config/sprout.yaml`. The conformance suite under `web-static/test/` compares the two
implementations' *outputs* over the eval cases, which catches a divergence only once the
committed config makes one visible. These tests catch the two divergences that were
structural — present in the code regardless of what the config happens to say today:

* **The confidence fit never reached the browser (issue #108).** `confidence.py` reads
  `cfg.confidence.fit` when `sprout fit-confidence` (ADR-0016) has written one. The
  export never emitted it, `ConfidenceConfig` in TypeScript had no field for it, and
  `scoreConfidence()` never read config at all. No fit is committed today, so nothing
  diverged yet; the first use of the documented workflow would have made the browser and
  the CLI disagree about abstention, silently, with the conformance fixtures regenerated
  from Python and therefore agreeing with neither surface's intent.

* **Safety routing compared against an English literal (issue #107).** Both sides now
  read a shared bilingual slug set, which only helps if the two sets stay equal.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from sprout.chunk import SAFETY_TOPIC_SLUGS
from sprout.config import load_config

_ROOT = Path(__file__).resolve().parent.parent
_EXPORT = _ROOT / "scripts" / "export_web_bundle.py"
_TS_TOPICS = _ROOT / "web-static" / "src" / "topics.ts"
_TS_CONFIG = _ROOT / "web-static" / "src" / "config.ts"
_TS_CONFIDENCE = _ROOT / "web-static" / "src" / "confidence.ts"


def _ts_string_set(source: str, name: str) -> set[str]:
    """The string literals in `export const <name>: ... = new Set([...])`."""
    match = re.search(rf"export const {name}[^=]*=\s*new Set\(\[(.*?)\]\)", source, re.S)
    assert match, f"{name} not found as a `new Set([...])` literal"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_the_two_safety_topic_slug_sets_are_equal() -> None:
    """A slug in one and not the other is a language where routing silently differs."""
    ts = _ts_string_set(_TS_TOPICS.read_text(encoding="utf-8"), "SAFETY_TOPIC_SLUGS")
    assert ts == set(SAFETY_TOPIC_SLUGS), {
        "only in TypeScript": sorted(ts - set(SAFETY_TOPIC_SLUGS)),
        "only in Python": sorted(set(SAFETY_TOPIC_SLUGS) - ts),
    }


def test_the_slug_set_covers_every_toxicity_heading_the_corpus_actually_uses() -> None:
    """Derived from the corpus, not from the set, so a new heading fails this.

    A hand-maintained set is only as good as the documents it was written against. This
    reads every `## `-level heading in the processed corpus whose slug the routing must
    recognise -- the toxicity sections -- and asserts the set covers them.
    """
    processed = _ROOT / "corpus" / "processed"
    documents = sorted(processed.glob("*.md"))
    assert len(documents) >= 16, f"only {len(documents)} corpus documents found"
    from sprout.chunk import slugify

    headings = {
        slugify(line[3:].strip())
        for path in documents
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ") and line[3:].strip().lower().startswith(("tox", "safe", "segur"))
    }
    assert headings, "no toxicity headings found in the corpus; this check would be vacuous"
    assert headings <= set(SAFETY_TOPIC_SLUGS), sorted(headings - set(SAFETY_TOPIC_SLUGS))


def test_the_typescript_confidence_config_declares_the_fit() -> None:
    source = _TS_CONFIG.read_text(encoding="utf-8")
    assert "interface ConfidenceFit" in source
    assert re.search(r"interface ConfidenceConfig\s*\{[^}]*\bfit\b", source, re.S), (
        "ConfidenceConfig has no `fit` field, so an exported fit has nowhere to land"
    )


def test_the_typescript_score_confidence_reads_the_fit_rather_than_module_constants() -> None:
    source = _TS_CONFIDENCE.read_text(encoding="utf-8")
    assert "cfg?.fit" in source or "cfg.fit" in source, (
        "scoreConfidence never reads the config's fit, so a committed fit changes the "
        "CLI's answer and not the browser's"
    )
    signature = re.search(r"export function scoreConfidence\((.*?)\)\s*:", source, re.S)
    assert signature and "ConfidenceConfig" in signature.group(1), (
        "scoreConfidence does not accept a ConfidenceConfig"
    )


def test_the_exported_bundle_carries_the_confidence_fit(tmp_path: Path) -> None:
    """Run the real exporter and read what it wrote.

    Checking the source for the word "fit" would pass on a comment. This runs
    `scripts/export_web_bundle.py` and asserts the key is present in the JSON, and that
    its value is what `config/sprout.yaml` says -- `null` while no fit is committed,
    the three constants once one is.
    """
    out = tmp_path / "public" / "data"
    # The exporter copies the built index verbatim; a stub is enough, and keeps this
    # test from needing `make ingest` to have run. The CI `test` job does not ingest,
    # and depending on `var/index.json` made this pass locally and fail there.
    stub_index = tmp_path / "index.json"
    stub_index.write_text('{"chunks": []}\n', encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(_EXPORT),
            "--config",
            str(_ROOT / "config" / "sprout.yaml"),
            "--index",
            str(stub_index),
            "--out",
            str(out),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    exported = json.loads((out / "config.json").read_text(encoding="utf-8"))["confidence"]
    assert "fit" in exported, (
        "the exported bundle has no `confidence.fit` key at all, so a committed fit "
        "cannot reach the browser however the TypeScript is written"
    )

    committed = load_config(_ROOT / "config" / "sprout.yaml").confidence.fit
    if committed is None:
        assert exported["fit"] is None
    else:
        assert exported["fit"] == {
            "midpoint": committed.midpoint,
            "steepness": committed.steepness,
            "margin_bonus": committed.margin_bonus,
        }
