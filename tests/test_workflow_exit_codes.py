"""A workflow step cannot read `$?` from a command that already aborted the step.

GitHub runs `run:` blocks under `bash -e {0}` by default. `-e` is applied by the shell's
own invocation, and a `set -uo pipefail` line inside the block cannot remove it — `set +e`
can, `set -uo pipefail` cannot, and the difference is invisible on a green run.

So this shape is dead code:

    some-command
    rc="$?"          # never reached when some-command fails
    ...              # neither is anything below it

and it is dead on exactly the runs it was written for. `live-integrity.yml` carried it:
its deploy-race excuse, and the verifier's own `exit 4` vs `exit 1` distinction, were
unreachable whenever the verifier actually failed. The sibling repo
(`transit-delivery-atlas`) hit the same bug, fixed it, and wrote down why; this repository's
copy never got the fix, which is the argument for a check rather than a memory.

The correct idiom captures the status on the same command:

    rc=0
    some-command || rc=$?
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))

#: `rc="$?"` / `rc=$?` as a statement of its own, i.e. not attached to a `||` on the same
#: line. The attached form is the correct idiom and must keep working.
_DETACHED_STATUS_READ = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*=\"?\$\?\"?\s*$", re.MULTILINE)

#: `set +e` genuinely disables `-e`, so a block that does it may read `$?` on its own line.
_DISABLES_ERREXIT = re.compile(r"^\s*set\s+[+][A-Za-z]*e", re.MULTILINE)


def _run_blocks() -> list[tuple[Path, str, str]]:
    """Every `run:` script in every workflow, with the job and step it belongs to."""

    blocks: list[tuple[Path, str, str]] = []
    for path in _WORKFLOWS:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (document.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                script = step.get("run")
                if isinstance(script, str):
                    blocks.append((path, f"{job_name}/{step.get('name', 'unnamed')}", script))
    return blocks


def test_there_are_workflows_with_run_blocks_to_check() -> None:
    """Without this the sweep below would pass by having nothing to sweep."""

    blocks = _run_blocks()
    assert _WORKFLOWS, "no workflow files found; every check in this file would be vacuous"
    assert len(blocks) > 20, f"only {len(blocks)} run blocks found; the parser is not working"


@pytest.mark.parametrize(
    ("path", "step", "script"),
    [pytest.param(*block, id=f"{block[0].name}:{block[1]}") for block in _run_blocks()],
)
def test_no_step_reads_a_status_a_failing_command_never_returns(
    path: Path, step: str, script: str
) -> None:
    if _DISABLES_ERREXIT.search(script):
        return
    offenders = _DETACHED_STATUS_READ.findall(script)
    assert not offenders, (
        f"{path.name} step {step!r} assigns from $? on its own line. Under the default "
        "`bash -e` shell the preceding command aborts the step when it fails, so that "
        "assignment and everything after it is unreachable exactly when it matters. "
        "Write `rc=0` then `some-command || rc=$?`, or `set +e` if the whole block needs it."
    )


def test_the_live_integrity_step_captures_the_verifier_status_on_the_command() -> None:
    """The specific step this check was written for, pinned by its shape rather than its text."""

    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / ".github/workflows/live-integrity.yml").read_text(
            encoding="utf-8"
        )
    )
    scripts = [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if isinstance(step.get("run"), str) and "verify_live_site.py" in step["run"]
    ]

    assert scripts, "no step runs verify_live_site.py; this check would be vacuous"
    for script in scripts:
        assert re.search(r"verify_live_site\.py[^\n]*\|\|\s*verify_rc=\$\?", script), (
            "the verifier's exit status must be captured on the same line as the command"
        )
        assert 'exit "$verify_rc"' in script, "the captured status must still decide the step"
