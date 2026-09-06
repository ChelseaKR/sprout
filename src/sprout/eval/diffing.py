"""Compare two eval reports and say which cases flipped, and why.

``sprout eval`` checks a run against the committed baseline, ``--drift-k`` watches a
decline streak across the history ledger, and ``--update-baseline`` adopts a new run.
None of them says *why* a case flipped, so a red eval step named a suite and the
maintainer opened two JSON files to find the case. ``sprout eval-diff`` is that step.

Two things shape what it is willing to claim.

**A report records only its failing examples.** ``SuiteResult.failing_examples`` is the
whole per-case record; a passing case leaves no trace. So "absent from the later report's
failures" normally means the case passed — but it means that *only* when both reports ran
the same cases. If ``dataset_hash`` differs, a case that disappeared may have been removed
from the suite rather than fixed, and the two are indistinguishable from the report alone.
Calling that "fixed" would be the portfolio's dominant defect — an absence published as a
measurement — so a differing dataset hash downgrades every disappearance to
``not_comparable`` and says why.

**A different judge or target produces different numbers.** When ``judge_config_hash``,
``target`` or ``harness_version`` differ, the score and interval deltas are refused with
the two hashes named rather than printed as though they measured the same thing. Flips are
still listed, because "this case failed there and not here" stays meaningful across a
judge change even when the arithmetic does not.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from .runner import RunFingerprint, RunResult
from .suite import ExampleOutcome, SuiteResult, Verdict


class Comparability(StrEnum):
    """Why two reports' numbers may or may not be compared."""

    COMPARABLE = "comparable"
    DATASET_CHANGED = "dataset_changed"
    JUDGE_CHANGED = "judge_changed"
    TARGET_CHANGED = "target_changed"
    HARNESS_CHANGED = "harness_changed"


#: Fingerprint fields whose difference makes the *numbers* incomparable, and the
#: `Comparability` each one raises. `seed` is deliberately absent: the deterministic
#: target ignores it, and a seed change is visible in the report itself.
_BLOCKING_FIELDS: tuple[tuple[str, Comparability], ...] = (
    ("dataset_hash", Comparability.DATASET_CHANGED),
    ("judge_config_hash", Comparability.JUDGE_CHANGED),
    ("target", Comparability.TARGET_CHANGED),
    ("harness_version", Comparability.HARNESS_CHANGED),
)


class CaseChange(StrEnum):
    """What happened to one case between the two reports."""

    #: Failing in the earlier report, not failing in the later one.
    FIXED = "fixed"
    #: Not failing in the earlier report, failing in the later one.
    BROKEN = "broken"
    #: Failing in both, with the recorded check result unchanged.
    STILL_FAILING = "still_failing"
    #: Failing in both, but the recorded reason or score moved.
    STILL_FAILING_DIFFERENT_REASON = "still_failing_different_reason"
    #: Present on one side only, with no way to tell absence from a pass.
    NOT_COMPARABLE = "not_comparable"


class SuiteChange(StrEnum):
    """What happened to one suite between the two reports."""

    PRESENT_IN_BOTH = "present_in_both"
    ONLY_BEFORE = "only_before"
    ONLY_AFTER = "only_after"


class CaseDelta(BaseModel):
    """One case's outcome across the two reports."""

    model_config = {"frozen": True}

    suite: str
    item_id: str
    change: CaseChange
    before_score: float | None = None
    after_score: float | None = None
    before_detail: str = ""
    after_detail: str = ""
    reason: str = ""

    @property
    def is_regression(self) -> bool:
        return self.change is CaseChange.BROKEN


class SegmentDelta(BaseModel):
    """One segment's score across the two reports.

    For ``calibration`` these segments are the confidence bins, so the list of them is the
    coverage-risk curve and this is its delta.
    """

    model_config = {"frozen": True}

    label: str
    before_score: float | None = None
    after_score: float | None = None
    before_n: int | None = None
    after_n: int | None = None
    before_verdict: Verdict | None = None
    after_verdict: Verdict | None = None


class SuiteDelta(BaseModel):
    """One suite's numbers, verdict and case flips across the two reports."""

    model_config = {"frozen": True}

    suite: str
    change: SuiteChange
    before_verdict: Verdict | None = None
    after_verdict: Verdict | None = None
    before_score: float | None = None
    after_score: float | None = None
    score_delta: float | None = None
    intervals_overlap: bool | None = None
    before_interval: tuple[float, float] | None = None
    after_interval: tuple[float, float] | None = None
    before_n: int | None = None
    after_n: int | None = None
    numbers_comparable: bool = True
    cases: tuple[CaseDelta, ...] = ()
    segments: tuple[SegmentDelta, ...] = ()

    @property
    def verdict_regressed(self) -> bool:
        return (
            self.before_verdict is Verdict.PASS
            and self.after_verdict is not None
            and self.after_verdict is not Verdict.PASS
        )

    @property
    def moved_cases(self) -> tuple[CaseDelta, ...]:
        return tuple(case for case in self.cases if case.change is not CaseChange.STILL_FAILING)

    @property
    def moved(self) -> bool:
        """Did anything about this suite change?

        Written against the raw scores rather than ``score_delta``, because the delta is
        ``None`` exactly when the two runs are not numerically comparable — and that is
        the case where a suite's score moving matters most. Reading the delta here would
        make an incomparable run report "nothing moved".
        """

        return bool(
            self.change is not SuiteChange.PRESENT_IN_BOTH
            or self.moved_cases
            or self.segments
            or self.before_verdict != self.after_verdict
            or self.before_score != self.after_score
            or self.before_n != self.after_n
        )


class ReportDiff(BaseModel):
    """The whole comparison, as a JSON-serializable record."""

    model_config = {"frozen": True}

    before: RunFingerprint
    after: RunFingerprint
    before_verdict: Verdict
    after_verdict: Verdict
    blocking: tuple[Comparability, ...] = ()
    suites: tuple[SuiteDelta, ...] = ()

    @property
    def numbers_comparable(self) -> bool:
        return not self.blocking

    @property
    def regressions(self) -> tuple[CaseDelta, ...]:
        return tuple(case for suite in self.suites for case in suite.cases if case.is_regression)

    @property
    def regressed_suites(self) -> tuple[SuiteDelta, ...]:
        return tuple(suite for suite in self.suites if suite.verdict_regressed)

    @property
    def moved(self) -> bool:
        return any(suite.moved for suite in self.suites)


def load_report(raw: str) -> RunResult:
    """Parse one eval report. Raises ``ValueError`` when it is not one."""

    return RunResult.model_validate_json(raw)


def _blocking(before: RunFingerprint, after: RunFingerprint) -> tuple[Comparability, ...]:
    return tuple(
        reason
        for field, reason in _BLOCKING_FIELDS
        if getattr(before, field) != getattr(after, field)
    )


def _intervals_overlap(before: tuple[float, float], after: tuple[float, float]) -> bool:
    return before[0] <= after[1] and after[0] <= before[1]


def _case_deltas(
    suite: str,
    before: SuiteResult | None,
    after: SuiteResult | None,
    *,
    dataset_changed: bool,
) -> tuple[CaseDelta, ...]:
    before_failures: dict[str, ExampleOutcome] = (
        {outcome.item_id: outcome for outcome in before.failing_examples} if before else {}
    )
    after_failures: dict[str, ExampleOutcome] = (
        {outcome.item_id: outcome for outcome in after.failing_examples} if after else {}
    )
    deltas: list[CaseDelta] = []
    for item_id in sorted(set(before_failures) | set(after_failures)):
        left, right = before_failures.get(item_id), after_failures.get(item_id)
        if left is not None and right is not None:
            same = (
                left.passed == right.passed
                and left.score == right.score
                and (left.detail == right.detail)
            )
            deltas.append(
                CaseDelta(
                    suite=suite,
                    item_id=item_id,
                    change=(
                        CaseChange.STILL_FAILING
                        if same
                        else CaseChange.STILL_FAILING_DIFFERENT_REASON
                    ),
                    before_score=left.score,
                    after_score=right.score,
                    before_detail=left.detail,
                    after_detail=right.detail,
                )
            )
            continue
        if left is not None:
            # It failed before and is not among the later failures. That is a fix only if
            # the later run held the same cases; otherwise the case may simply be gone,
            # and a report cannot tell the two apart.
            if dataset_changed or after is None:
                deltas.append(
                    CaseDelta(
                        suite=suite,
                        item_id=item_id,
                        change=CaseChange.NOT_COMPARABLE,
                        before_score=left.score,
                        before_detail=left.detail,
                        reason=(
                            "the later report did not run this suite"
                            if after is None
                            else "the dataset hash changed, so a case that stopped failing "
                            "cannot be told apart from a case that was removed"
                        ),
                    )
                )
            else:
                deltas.append(
                    CaseDelta(
                        suite=suite,
                        item_id=item_id,
                        change=CaseChange.FIXED,
                        before_score=left.score,
                        before_detail=left.detail,
                    )
                )
            continue
        assert right is not None
        if before is None:
            deltas.append(
                CaseDelta(
                    suite=suite,
                    item_id=item_id,
                    change=CaseChange.NOT_COMPARABLE,
                    after_score=right.score,
                    after_detail=right.detail,
                    reason="the earlier report did not run this suite",
                )
            )
        else:
            # A new failure is a new failure whether or not the dataset moved: the later
            # report records it failing. Only its *absence* was ambiguous.
            deltas.append(
                CaseDelta(
                    suite=suite,
                    item_id=item_id,
                    change=CaseChange.BROKEN,
                    after_score=right.score,
                    after_detail=right.detail,
                )
            )
    return tuple(deltas)


def _segment_deltas(
    before: SuiteResult | None, after: SuiteResult | None
) -> tuple[SegmentDelta, ...]:
    left = {segment.label: segment for segment in before.segments} if before else {}
    right = {segment.label: segment for segment in after.segments} if after else {}
    return tuple(
        SegmentDelta(
            label=label,
            before_score=left[label].score if label in left else None,
            after_score=right[label].score if label in right else None,
            before_n=left[label].n if label in left else None,
            after_n=right[label].n if label in right else None,
            before_verdict=left[label].verdict if label in left else None,
            after_verdict=right[label].verdict if label in right else None,
        )
        for label in sorted(set(left) | set(right))
        if left.get(label) != right.get(label)
    )


def diff_reports(before: RunResult, after: RunResult) -> ReportDiff:
    """Compare two loaded eval reports. Pure; reads no clock and no file."""

    blocking = _blocking(before.fingerprint, after.fingerprint)
    numbers_comparable = not blocking
    dataset_changed = Comparability.DATASET_CHANGED in blocking
    left = {result.suite: result for result in before.suite_results}
    right = {result.suite: result for result in after.suite_results}

    suites: list[SuiteDelta] = []
    for name in sorted(set(left) | set(right)):
        one, two = left.get(name), right.get(name)
        if one is not None and two is not None:
            change = SuiteChange.PRESENT_IN_BOTH
        elif one is not None:
            change = SuiteChange.ONLY_BEFORE
        else:
            change = SuiteChange.ONLY_AFTER
        both = one is not None and two is not None
        compare_numbers = numbers_comparable and both
        suites.append(
            SuiteDelta(
                suite=name,
                change=change,
                before_verdict=one.verdict if one else None,
                after_verdict=two.verdict if two else None,
                before_score=one.score if one else None,
                after_score=two.score if two else None,
                score_delta=(
                    round(two.score - one.score, 6) if compare_numbers and one and two else None
                ),
                intervals_overlap=(
                    _intervals_overlap((one.ci_low, one.ci_high), (two.ci_low, two.ci_high))
                    if compare_numbers and one and two
                    else None
                ),
                before_interval=(one.ci_low, one.ci_high) if one else None,
                after_interval=(two.ci_low, two.ci_high) if two else None,
                before_n=one.n_items if one else None,
                after_n=two.n_items if two else None,
                numbers_comparable=compare_numbers,
                cases=_case_deltas(name, one, two, dataset_changed=dataset_changed),
                segments=_segment_deltas(one, two),
            )
        )

    return ReportDiff(
        before=before.fingerprint,
        after=after.fingerprint,
        before_verdict=before.overall_verdict,
        after_verdict=after.overall_verdict,
        blocking=blocking,
        suites=tuple(suites),
    )


def exit_code_for(diff: ReportDiff, *, fail_on_regression: bool) -> int:
    """``1`` only when asked to fail and something actually regressed."""

    if not fail_on_regression:
        return 0
    return 1 if diff.regressions or diff.regressed_suites else 0


_BLOCKING_PROSE: dict[Comparability, str] = {
    Comparability.DATASET_CHANGED: "dataset_hash",
    Comparability.JUDGE_CHANGED: "judge_config_hash",
    Comparability.TARGET_CHANGED: "target",
    Comparability.HARNESS_CHANGED: "harness_version",
}

_CASE_PROSE: dict[CaseChange, str] = {
    CaseChange.FIXED: "fixed",
    CaseChange.BROKEN: "broken",
    CaseChange.STILL_FAILING: "still failing",
    CaseChange.STILL_FAILING_DIFFERENT_REASON: "still failing, different reason",
    CaseChange.NOT_COMPARABLE: "not comparable",
}


def _fingerprint_lines(diff: ReportDiff) -> list[str]:
    lines = ["| field | earlier | later |", "| --- | --- | --- |"]
    for field, _reason in _BLOCKING_FIELDS:
        before = getattr(diff.before, field)
        after = getattr(diff.after, field)
        marker = "" if before == after else " **(differs)**"
        lines.append(f"| `{field}` | `{before}` | `{after}`{marker} |")
    return lines


def _suite_is_quiet(suite: SuiteDelta) -> bool:
    """Nothing about this suite moved, so it has nothing to say."""

    return not suite.moved


def _suite_heading_lines(suite: SuiteDelta) -> list[str]:
    if suite.change is not SuiteChange.PRESENT_IN_BOTH:
        side = "earlier" if suite.change is SuiteChange.ONLY_BEFORE else "later"
        return [f"## {suite.suite}", "", f"Ran in the {side} report only.", ""]
    verdicts = (
        f"`{suite.before_verdict.value}` → `{suite.after_verdict.value}`"
        if suite.before_verdict and suite.after_verdict
        else "—"
    )
    if suite.numbers_comparable and suite.score_delta is not None:
        overlap = "overlap" if suite.intervals_overlap else "do not overlap"
        summary = (
            f"Verdict {verdicts}. Score {suite.before_score} → {suite.after_score} "
            f"(Δ {suite.score_delta:+g}); 95% intervals {overlap} "
            f"({suite.before_interval} vs {suite.after_interval}); "
            f"n {suite.before_n} → {suite.after_n}."
        )
    else:
        summary = (
            f"Verdict {verdicts}. Score {suite.before_score} and {suite.after_score} are "
            "shown side by side; no difference is computed, for the reason above."
        )
    return [f"## {suite.suite}", "", summary, ""]


def _case_table_lines(suite: SuiteDelta) -> list[str]:
    if not suite.moved_cases:
        return []
    lines = ["| case | change | detail |", "| --- | --- | --- |"]
    for case in suite.moved_cases:
        detail = (case.reason or case.after_detail or case.before_detail or "").replace("|", "\\|")
        lines.append(f"| `{case.item_id}` | {_CASE_PROSE[case.change]} | {detail} |")
    lines.append("")
    return lines


def _segment_table_lines(suite: SuiteDelta) -> list[str]:
    if not suite.segments:
        return []
    return [
        "| segment | score | n |",
        "| --- | --- | --- |",
        *(
            f"| `{segment.label}` | {segment.before_score} → {segment.after_score} "
            f"| {segment.before_n} → {segment.after_n} |"
            for segment in suite.segments
        ),
        "",
    ]


def _blocking_lines(diff: ReportDiff) -> list[str]:
    if not diff.blocking:
        return []
    named = ", ".join(f"`{_BLOCKING_PROSE[reason]}`" for reason in diff.blocking)
    lines = [
        f"**Numeric deltas are refused: {named} differ.** Scores and intervals from these "
        "two runs do not measure the same thing, so this comparison prints them side by "
        "side and computes no difference. Case flips are still listed, because a case that "
        "failed in one run and not the other stays meaningful.",
        "",
    ]
    if Comparability.DATASET_CHANGED in diff.blocking:
        lines += [
            "Because the dataset hash changed, a case that stopped failing is reported as "
            "**not comparable** rather than fixed: a report records only its failures, so a "
            "case that was removed and a case that started passing look identical from here.",
            "",
        ]
    return lines


def render_markdown(diff: ReportDiff) -> str:
    """Deterministic Markdown. Ordering is by suite name, then case id."""

    lines = [
        "# Eval report comparison",
        "",
        f"Overall verdict: `{diff.before_verdict.value}` → `{diff.after_verdict.value}`",
        "",
        *_fingerprint_lines(diff),
        "",
        *_blocking_lines(diff),
    ]
    if not diff.moved:
        return "\n".join([*lines, "No suite and no case moved between these two reports.", ""])
    for suite in diff.suites:
        if _suite_is_quiet(suite):
            continue
        lines += [
            *_suite_heading_lines(suite),
            *_case_table_lines(suite),
            *_segment_table_lines(suite),
        ]
    return "\n".join(lines)
