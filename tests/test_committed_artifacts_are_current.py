"""Every committed artifact that stands in for a computation must equal its generator's
output — checked by regenerating into a temp directory and comparing bytes.

Before this file, ``docs/audits/gate-inventory.md`` was the only committed artifact with
such a gate (``tests/test_gate_inventory.py``). The eval report, the smoke report, the
corpus report, the judge-calibration record, the static-vector embedding table, and the
worked example's report all had none, and the way they were "checked" made a stale file
structurally undetectable:

* ``make verify`` runs ``make eval``/``smoke``/``corpus-report``/``calibrate``, whose
  recipes *write into* ``docs/audits/``. A stale committed report was silently rewritten
  in the working tree and the target exited 0, saying nothing.
* CI could not catch it either: the ``eval-a11y`` and ``smoke`` jobs run those same
  writing commands on a clean checkout, so they overwrite the committed evidence before
  anything reads it. ``sprout claims-check`` then validates the docs against the
  *regenerated* ``eval-report.json``, not the committed one.
* ``examples/herb-garden-plugin/report/`` had nothing at all, and had in fact drifted:
  its committed run was recorded against judge config ``b37ebf08157f`` and the current
  judge is ``ff1ad7874e00``.

So these tests regenerate into ``tmp_path`` and compare. They never write into the
working tree — a gate that heals drift where it finds it leaves the committed bytes
stale, which is the failure being gated.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from sprout.cli import app

_ROOT = Path(__file__).resolve().parents[1]
_AUDITS = _ROOT / "docs" / "audits"
_EXAMPLE = _ROOT / "examples" / "herb-garden-plugin"
_GENERATOR = _ROOT / "scripts" / "generate_static_vectors.py"
_EMBEDDINGS = _ROOT / "src" / "sprout" / "data" / "embeddings"
_EMBEDDINGS_MANIFEST = _EMBEDDINGS / "manifest.yaml"
_STATIC_VECTORS = _EMBEDDINGS / "static_vectors.json"

_runner = CliRunner()

_STALE = (
    "{name} is stale: it is not what the generator now produces. Regenerate it "
    "({how}) and commit the result — do not hand-edit it."
)


def _assert_same(committed: Path, regenerated: Path, how: str) -> None:
    """Byte-compare, with a first-difference excerpt when they disagree."""
    assert committed.exists(), f"{committed} is not committed; run {how}"
    assert regenerated.exists(), f"the regeneration did not produce {regenerated.name}"
    want, got = committed.read_bytes(), regenerated.read_bytes()
    if want == got:
        return
    detail = ""
    try:
        want_lines = want.decode("utf-8").splitlines()
        got_lines = got.decode("utf-8").splitlines()
        for i, (a, b) in enumerate(zip(want_lines, got_lines, strict=False), start=1):
            if a != b:
                # The HTML report is one very long line; show a window around the first
                # differing character rather than dumping the whole document twice.
                col = next(
                    (c for c, (x, y) in enumerate(zip(a, b, strict=False)) if x != y),
                    min(len(a), len(b)),
                )
                lo, hi = max(0, col - 60), col + 60
                detail = (
                    f"\n  first difference, line {i} col {col}:"
                    f"\n  committed: ...{a[lo:hi]!r}..."
                    f"\n  fresh:     ...{b[lo:hi]!r}..."
                )
                break
        else:
            detail = f"\n  line counts differ: committed {len(want_lines)}, fresh {len(got_lines)}"
    except UnicodeDecodeError:  # pragma: no cover - every artifact here is text
        detail = ""
    raise AssertionError(_STALE.format(name=committed.relative_to(_ROOT), how=how) + detail)


@pytest.fixture(scope="session")
def regenerated_audits(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A fresh ``docs/audits`` built from the committed corpus, config and suites.

    Written to a temp directory, never to ``docs/audits``. The config is copied with only
    ``store.path`` redirected, so the run does not need ``make ingest`` to have happened
    (the CI ``test`` job does not ingest) and does not leave ``var/index.json`` behind.
    """
    work = tmp_path_factory.mktemp("regenerated-audits")
    out = work / "audits"
    out.mkdir()

    config = yaml.safe_load((_ROOT / "config" / "sprout.yaml").read_text(encoding="utf-8"))
    config["store"]["path"] = str(work / "index.json")
    config_path = work / "sprout.yaml"
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    # The committed baseline goes in so the run takes exactly the path `make eval` takes,
    # baseline regression check included, rather than the "no baseline, skipping" branch.
    shutil.copy2(_AUDITS / "eval-baseline.json", out / "eval-baseline.json")

    for argv in (
        ["ingest", "--config", str(config_path)],
        ["eval", "--config", str(config_path), "--out", str(out)],
        ["smoke", "--config", str(config_path), "--out", str(out)],
        ["corpus-report", "--config", str(config_path), "--out", str(out)],
        ["calibrate", "eval/judge_probes.yaml", "--out", str(out), "--gate"],
    ):
        result = _runner.invoke(app, argv)
        assert result.exit_code == 0, (
            f"`sprout {' '.join(argv)}` exited {result.exit_code} while regenerating the "
            f"committed audits:\n{result.output}"
        )
    return out


#: Committed ``docs/audits`` artifact -> the command that regenerates it.
_GATED_AUDITS = {
    "eval-report.json": "`make eval`",
    "eval-report.md": "`make eval`",
    "eval-report.html": "`make eval`",
    "eval-report.junit.xml": "`make eval`",
    "eval-report.sarif": "`make eval`",
    "smoke-report.md": "`make smoke`",
    "corpus-report.json": "`make corpus-report`",
    "corpus-report.md": "`make corpus-report`",
    "judge-calibration.json": "`make calibrate`",
    "judge-calibration.md": "`make calibrate`",
    "gate-inventory.md": "`make gate-inventory`",  # gated in tests/test_gate_inventory.py
}

#: Committed under ``docs/audits`` and machine-shaped, but deliberately not regenerated here.
_UNGATED_AUDITS = {
    # A pinned prior run, refreshed only by `sprout eval --update-baseline`. Regenerating
    # it would erase the very thing it exists to compare against; `sprout eval` already
    # fails when it is stale relative to the current run's fingerprint (cli.py's
    # baseline check), and CI runs that on every PR.
    "eval-baseline.json",
}


@pytest.mark.parametrize("name", sorted(set(_GATED_AUDITS) - {"gate-inventory.md"}))
def test_committed_audit_matches_a_fresh_run(name: str, regenerated_audits: Path) -> None:
    _assert_same(_AUDITS / name, regenerated_audits / name, _GATED_AUDITS[name])


def test_every_committed_audit_artifact_is_covered() -> None:
    """The list above is hand-written; this stops it going quietly short.

    A new machine-generated file under ``docs/audits/`` must either be gated or be named
    in ``_UNGATED_AUDITS`` with a reason, so "not in the list" can never pass for "checked".
    """
    tracked = subprocess.run(
        ["git", "ls-files", "docs/audits"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert tracked, "git ls-files docs/audits returned nothing; this check would be vacuous"
    machine_made = {
        Path(p).name
        for p in tracked
        if Path(p).suffix in {".json", ".html", ".xml", ".sarif"}
        or Path(p).name.endswith(("-report.md", "-inventory.md", "-calibration.md"))
    }
    missing = sorted(machine_made - set(_GATED_AUDITS) - _UNGATED_AUDITS)
    assert not missing, (
        f"committed generated artifact(s) under docs/audits with no regeneration gate: "
        f"{missing}. Add each to _GATED_AUDITS, or to _UNGATED_AUDITS with a reason."
    )


def test_static_vector_table_matches_its_generator() -> None:
    """``src/sprout/data/embeddings/static_vectors.json`` vs ``clusters.yaml``.

    Runs the real generator's ``--check`` mode, which renders through the same serialiser
    ``main()`` writes with and compares without touching the file. Editing ``clusters.yaml``
    and forgetting to regenerate previously shipped a table the code no longer produces,
    with every gate green.
    """
    completed = subprocess.run(
        [sys.executable, str(_GENERATOR), "--check"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_static_vector_manifest_describes_the_table_it_ships_with() -> None:
    """`embeddings/manifest.yaml` restates the table's dimension and names its producer.

    Its `dim:` is a figure copied by hand out of a generated file, and its three path
    fields are claims about a pipeline. Both rot silently: a regenerated table with a
    different dimension, or a renamed generator, leaves the provenance record describing
    something that no longer exists.
    """
    manifest = yaml.safe_load(_EMBEDDINGS_MANIFEST.read_text(encoding="utf-8"))
    table = json.loads(_STATIC_VECTORS.read_text(encoding="utf-8"))
    assert manifest["dim"] == table["dim"], (
        f"{_EMBEDDINGS_MANIFEST.relative_to(_ROOT)} says dim {manifest['dim']} where "
        f"{_STATIC_VECTORS.relative_to(_ROOT)} holds {table['dim']}"
    )
    assert manifest["generator"] == table["generator"] == "scripts/generate_static_vectors.py"
    assert manifest["source_file"] == table["source"]
    for field, path in (
        ("source_file", _EMBEDDINGS_MANIFEST.parent / str(manifest["source_file"])),
        ("generated_file", _EMBEDDINGS_MANIFEST.parent / str(manifest["generated_file"])),
        ("generator", _ROOT / str(manifest["generator"])),
        ("adr", _ROOT / str(manifest["adr"])),
    ):
        assert path.exists(), (
            f"{_EMBEDDINGS_MANIFEST.relative_to(_ROOT)} names {field}={manifest[field]!r}, "
            f"which does not exist at {path}"
        )


_EXAMPLE_OUTPUTS = (
    "report/eval-report.json",
    "report/eval-report.md",
    "report/eval-report.html",
    "report/eval-report.junit.xml",
    "report/eval-report.sarif",
    "eval/suites.sha256",
)

# `run_example.py` chdir()s to its own directory and writes in place, so it is run against
# a *copy* under tmp_path. The plugin suite is registered by hand rather than through the
# `sprout.eval.suites` entry point, because the example package is not a dev dependency and
# CI never installs it; registering it directly gives the same report (verified
# byte-for-byte against `uv pip install -e examples/herb-garden-plugin` + the documented
# command) without a gate that can only run on a developer's machine.
_RUN_EXAMPLE = """
import runpy, sys
sys.path.insert(0, {src!r})
from sprout.eval.suite import register
from herb_garden_eval.suite import build_suite
register(build_suite())
runpy.run_path({script!r}, run_name="__main__")
"""


@pytest.fixture(scope="session")
def regenerated_example(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A fresh run of the EXP-14 worked example, in a copy of it under tmp."""
    work = tmp_path_factory.mktemp("herb-garden") / "plugin"
    # The committed outputs are excluded from the copy: with them present, a run that
    # crashed early would leave them in place and every comparison below would pass
    # against the very bytes under test.
    shutil.copytree(_EXAMPLE, work, ignore=shutil.ignore_patterns("report"))
    (work / "eval" / "suites.sha256").unlink()

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _RUN_EXAMPLE.format(src=str(work / "src"), script=str(work / "run_example.py")),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # `run_example.py` exits non-zero on purpose: the example's `calibration` suite fails
    # its threshold, and the committed report records that failure. So the exit code says
    # nothing about whether the run worked; the outputs existing does.
    for rel in _EXAMPLE_OUTPUTS:
        assert (work / rel).exists(), (
            f"the worked example did not produce {rel} (exit {completed.returncode}):\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return work


@pytest.mark.parametrize("rel", _EXAMPLE_OUTPUTS)
def test_worked_example_output_matches_a_fresh_run(rel: str, regenerated_example: Path) -> None:
    """The example's README promises these are byte-identical to a rerun. Now something checks.

    They were not: the committed report was recorded against judge config `b37ebf08157f`
    and dataset hash `7eebd2b8e764adc9`, both since superseded.
    """
    _assert_same(
        _EXAMPLE / rel,
        regenerated_example / rel,
        "`uv pip install -e examples/herb-garden-plugin && "
        "uv run python examples/herb-garden-plugin/run_example.py`",
    )
