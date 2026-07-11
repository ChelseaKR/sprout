"""Marker-hygiene ratchet — CQ-34 (partial; see note below for CQ-35).

Bare ``TODO``/``FIXME``/``HACK`` markers without a tracked-issue reference accumulate
silently over time. This test greps ``src/`` and ``tests/`` and fails if any such marker
appears on a line with no adjacent issue reference (``#123`` or a URL). The repo is clean
of bare markers today (2026-07-05); this test ratchets that state going forward rather than
only asserting it once in an audit.

**CQ-35 is intentionally NOT implemented here.** The full remediation-plan item also wanted
every ``# noqa: <code>`` / ``# type: ignore[<code>]`` to carry both a rule code *and* an
issue reference. This repo already has several such suppressions with a code but no issue
ref (e.g. ``src/sprout/config.py`` disclosure strings, several ``tests/`` files) that are
legitimate, reviewed suppressions, not drift. Gating on that today would either fail the
build on those pre-existing, defensible lines, or require inventing issue numbers to attach
to them — both worse than leaving this half of the ratchet as an acknowledged gap. Wire it
once those suppressions are actually triaged and given real issue links.
"""

from __future__ import annotations

import re
from pathlib import Path

_MARKER = re.compile(r"\b(TODO|FIXME|HACK)\b", re.IGNORECASE)
_HAS_REF = re.compile(r"#\d+|https?://")
_SELF = Path(__file__)


def _offenders() -> list[str]:
    offenders: list[str] = []
    for base in ("src", "tests"):
        for path in sorted(Path(base).rglob("*.py")):
            if path.resolve() == _SELF.resolve():
                continue  # this file's own docstring discusses the marker words
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if _MARKER.search(line) and not _HAS_REF.search(line):
                    offenders.append(f"{path}:{lineno}: {line.strip()}")
    return offenders


def test_no_untracked_todo_fixme_hack_markers() -> None:
    offenders = _offenders()
    assert not offenders, (
        "bare TODO/FIXME/HACK without a tracked-issue reference (#NNN or a URL):\n"
        + "\n".join(offenders)
    )
