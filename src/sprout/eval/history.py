"""The eval score history ledger — trend across releases, not just a single baseline diff.

``diff_against_baseline`` (see ``report.py``) compares a run against *one* pinned baseline;
a metric can decay a fraction of a point per release, forever, and never trip that tolerance
check. This module appends one entry per **release** (never per-PR, so the ledger stays a
release cadence, not a CI-noise stream) to ``docs/audits/eval-history.jsonl`` and derives a
drift rule from it: if any suite's score has *declined* for ``k`` consecutive releases in a
row, the release gate fails even if every individual decline was inside tolerance.

The ledger is a plain JSON-Lines file (one ``HistoryEntry`` per line, oldest first) so it
diffs and greps like any other append-only audit log, and a corrupt or truncated tail never
loses the entries before it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from itertools import pairwise
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .runner import RunResult
from .suite import Verdict


class SuiteScore(BaseModel):
    """One suite's score as recorded in a single release's history entry."""

    model_config = ConfigDict(frozen=True)

    suite: str
    score: float
    verdict: Verdict
    threshold: float
    higher_is_better: bool
    n_items: int


class HistoryEntry(BaseModel):
    """One release's fingerprinted suite scores — a single line of ``eval-history.jsonl``."""

    model_config = ConfigDict(frozen=True)

    release: str
    recorded_date: str
    fingerprint_digest: str
    harness_version: str
    target: str
    overall_verdict: Verdict
    suites: tuple[SuiteScore, ...]

    def score_for(self, suite: str) -> SuiteScore | None:
        return next((s for s in self.suites if s.suite == suite), None)


def history_entry_from_result(
    result: RunResult, *, release: str, recorded_date: date | None = None
) -> HistoryEntry:
    """Build the history entry for ``result``, tagged with the release identifier (e.g. a tag)."""
    return HistoryEntry(
        release=release,
        recorded_date=(recorded_date or date.today()).isoformat(),
        fingerprint_digest=result.fingerprint.digest,
        harness_version=result.fingerprint.harness_version,
        target=result.fingerprint.target,
        overall_verdict=result.overall_verdict,
        suites=tuple(
            SuiteScore(
                suite=s.suite,
                score=s.score,
                verdict=s.verdict,
                threshold=s.metric.threshold,
                higher_is_better=s.metric.higher_is_better,
                n_items=s.n_items,
            )
            for s in result.suite_results
        ),
    )


def load_history(path: str | Path) -> list[HistoryEntry]:
    """Load the ledger, oldest first. A missing file is an empty ledger, not an error."""
    p = Path(path)
    if not p.exists():
        return []
    entries = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(HistoryEntry.model_validate_json(line))
    return entries


def append_history_entry(path: str | Path, entry: HistoryEntry) -> None:
    """Append one entry as a single JSON line. Never rewrites or reorders prior entries."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")


def check_drift(history: Sequence[HistoryEntry], *, k: int = 3) -> list[str]:
    """Fail-closed drift rule: flag any suite that declined for ``k`` consecutive releases.

    Each individual decline may be well inside ``diff_against_baseline``'s tolerance — this
    catches the slow bleed a single-baseline diff cannot see. Requires at least ``k + 1``
    releases carrying the suite; older ledgers (or a suite added partway through) are silently
    skipped for that suite rather than raising, since there is not yet a trajectory to judge.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    if len(history) < k + 1:
        return []
    window = history[-(k + 1) :]
    suite_names = sorted({s.suite for entry in window for s in entry.suites})
    issues: list[str] = []
    for name in suite_names:
        scores = [entry.score_for(name) for entry in window]
        if any(s is None for s in scores):
            continue  # suite not present in every release of the window; no trajectory yet
        present = [s for s in scores if s is not None]
        higher_is_better = present[-1].higher_is_better
        declines = [
            (cur.score < prev.score) if higher_is_better else (cur.score > prev.score)
            for prev, cur in pairwise(present)
        ]
        if all(declines):
            trajectory = " -> ".join(f"{s.score:.4f}" for s in present)
            issues.append(
                f"drift: suite `{name}` declined for {k} consecutive releases ({trajectory})"
            )
    return issues
