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

* **The verbalized confidence band never existed in the browser (EXP-06).** `answer.py`
  puts `confidence_band` and `confidence_band_label` on every answer and `server.py`
  sends both, so the served UI announces "well-supported (0.82)". The static port had
  neither field, so sprout.chelseakr.com announced "82% confidence" — the raw figure
  EXP-06 exists to gloss — and the conformance suite could not see the difference,
  because a field it does not compare is a field the two implementations are free to
  disagree on. The band's cut point is exported as data for the same reason the fit is:
  `derive_band_cutoff` re-derives it after each confidence re-fit, and a constant
  mirrored into TypeScript would keep the browser on the old cut point silently.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from sprout.chunk import SAFETY_TOPIC_SLUGS
from sprout.confidence import (
    _DEFAULT_WELL_SUPPORTED_CUTOFF,
    BAND_INSUFFICIENT_EVIDENCE,
    BAND_PARTIALLY_SUPPORTED,
    BAND_WELL_SUPPORTED,
)
from sprout.config import load_config
from sprout.ingest import build_index

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
    # This used to pass a stub `{"chunks": []}` file, because the exporter only copied
    # the index and never read it, and depending on `var/index.json` made the test pass
    # locally and fail in the CI `test` job, which does not ingest. The bundle now
    # records the index's chunk ids and refuses an index that is not the one this corpus
    # chunks to, so an empty stub is exactly the "every comparison is vacuously true"
    # input it must reject. Build a real index here instead — it still does not depend on
    # `make ingest` having run, and ingesting the committed corpus takes well under a
    # second.
    built_index = tmp_path / "index.json"
    build_index(load_config(_ROOT / "config" / "sprout.yaml")).save(built_index)
    completed = subprocess.run(
        [
            sys.executable,
            str(_EXPORT),
            "--config",
            str(_ROOT / "config" / "sprout.yaml"),
            "--index",
            str(built_index),
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


# --- The verbalized confidence band reaches the browser (EXP-06) ----------------------


def test_the_typescript_port_computes_a_confidence_band() -> None:
    """The port had the float and no band, and every conformance case still passed.

    Reading the source rather than the output because this is the structural half: a
    `confidenceBand` that does not exist cannot diverge on any particular question, it
    is simply absent, and an output comparison over fields the port lacks reports
    agreement.
    """
    source = _TS_CONFIDENCE.read_text(encoding="utf-8")
    body = re.search(r"export function confidenceBand\([^)]*\)[^{]*\{(.*?)\n\}", source, re.S)
    assert body, (
        "web-static has no `confidenceBand`, so the browser can state a confidence but "
        "not the calibrated language EXP-06 renders alongside it"
    )
    # The *body*, not the file. Measured while building this: replacing
    # `cfg.well_supported_cutoff` with the literal `0.9` left `well_supported_cutoff`
    # in the function's own doc comment, so a whole-file substring check passed while
    # 114 conformance cases failed. A check that a comment can satisfy is not a check.
    assert "well_supported_cutoff" in body.group(1), (
        "`confidenceBand` does not read the exported cut point, so it is banding "
        "against a number this repository did not give it"
    )


def test_the_typescript_answer_carries_both_band_fields() -> None:
    """The band has to reach the `Answer`, not just exist as a function nobody calls."""
    answer_src = (_ROOT / "web-static" / "src" / "answer.ts").read_text(encoding="utf-8")
    models_src = (_ROOT / "web-static" / "src" / "models.ts").read_text(encoding="utf-8")
    for field in ("confidence_band", "confidence_band_label"):
        assert field in models_src, f"`Answer` in models.ts has no `{field}`"
        assert f"{field}:" in answer_src, (
            f"`{field}` is declared on the TypeScript `Answer` but never populated, so "
            "every answer would carry the interface's default and not a computed band"
        )
    # `answer.py` bands the unrounded score and only then rounds for display; banding
    # `round4(confidence)` instead would disagree with Python exactly at a cut point.
    assert "confidenceBand(confidence," in answer_src, (
        "the port bands a value other than the raw confidence, which is where Python "
        "and the browser would differ precisely at the band boundary"
    )


def test_the_exported_bundle_carries_the_band_cutoff_and_labels(tmp_path: Path) -> None:
    """Run the real exporter and read what it wrote — a source grep would pass on a comment."""
    out = tmp_path / "public" / "data"
    built_index = tmp_path / "index.json"
    cfg = load_config(_ROOT / "config" / "sprout.yaml")
    build_index(cfg).save(built_index)
    completed = subprocess.run(
        [
            sys.executable,
            str(_EXPORT),
            "--config",
            str(_ROOT / "config" / "sprout.yaml"),
            "--index",
            str(built_index),
            "--out",
            str(out),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    bundle = json.loads((out / "config.json").read_text(encoding="utf-8"))

    assert bundle["confidence"]["well_supported_cutoff"] == _DEFAULT_WELL_SUPPORTED_CUTOFF, (
        "the browser is banding against a different cut point than `confidence_band` "
        "uses, so the two surfaces can place the same answer in different bands"
    )
    assert bundle["prompts"]["confidence_band_labels"] == cfg.prompts.confidence_band_labels, (
        "the exported band labels are not the configured ones, so the browser would "
        "announce different words than the served UI for the same band"
    )
    # Every band key the Python engine can produce must have a label in the bundle, in
    # every supported language. A key with no entry falls back to the key itself, which
    # a screen reader announces as `partially_supported` — a missing translation
    # rendered as user-facing copy.
    #
    # This assertion is the *only* thing that catches a missing translation, and that
    # was measured, not assumed: deleting the Spanish `partially_supported` label and
    # re-running the whole cross-language conformance suite left all 238 cases passing,
    # because both implementations fall back to English identically and agree perfectly
    # on the wrong word. A Spanish speaker would hear "partially supported — verify" in
    # an otherwise-Spanish answer and no output comparison could see it.
    for band in (BAND_WELL_SUPPORTED, BAND_PARTIALLY_SUPPORTED, BAND_INSUFFICIENT_EVIDENCE):
        labels = bundle["prompts"]["confidence_band_labels"].get(band, {})
        missing = [lang for lang in cfg.languages.supported if not labels.get(lang)]
        assert not missing, f"band {band!r} has no label in {missing}"
