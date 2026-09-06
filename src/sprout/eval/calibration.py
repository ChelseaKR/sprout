"""Judge calibration against human labels — agreement and Cohen's kappa.

A judge may only back a gate if it agrees with human labels. We run the judge over a small
set of human-labeled probes and report raw agreement plus Cohen's kappa (kappa guards
against high raw agreement that is really just label imbalance). The record is invalidated
the moment the judge's config hash changes — a re-configured judge must not be trusted on an
old calibration. This is the "10% human-agreement sample, agreement + Cohen's kappa" check.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from .judge import Judge

MIN_AGREEMENT = 0.8
MIN_KAPPA = 0.6


class JudgeProbe(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: str  # entails | contains | equivalent
    text_a: str
    text_b: str = ""
    sources: list[str] = []
    human_label: bool


class OpAgreement(BaseModel):
    model_config = ConfigDict(frozen=True)

    n: int
    n_agree: int
    agreement: float


class CalibrationError(ValueError):
    """Raised when calibration is asked to score something it cannot score."""


class CalibrationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    judge_method: str
    judge_config_hash: str
    n_probes: int
    n_agree: int
    agreement: float
    cohens_kappa: float
    per_operation: dict[str, OpAgreement]
    disagreements: tuple[str, ...]

    @property
    def meets_threshold(self) -> bool:
        """A record over no probes never meets the threshold, whatever it holds.

        `calibrate` now refuses an empty probe set outright, so a fresh record cannot
        reach this with ``n_probes == 0``. The floor stays here as well because a record
        is also loaded back from committed JSON (`sprout calibrate` writes
        ``judge-calibration.json``, and `is_stale` reads it), and a record written before
        this fix carries ``agreement`` and ``cohens_kappa`` of ``1.0`` over zero
        observations. Reading that as "meets" is the thing being fixed, so the check that
        a reader actually calls has to fail closed too.
        """

        return (
            self.n_probes > 0 and self.agreement >= MIN_AGREEMENT and self.cohens_kappa >= MIN_KAPPA
        )


def cohens_kappa(judge_labels: Sequence[bool], human_labels: Sequence[bool]) -> float:
    """Cohen's kappa for two binary label sequences. Degenerate expected-agreement -> 1.0.

    Raises :class:`CalibrationError` on empty input. κ over no observations is not 1.0 and
    is not 0.0; it is undefined, and the two degenerate cases are not the same thing. When
    every label agrees and expected agreement is therefore 1.0 (below), perfect agreement
    was *observed* and κ of 1.0 is the correct reading of it. When there are no labels,
    nothing was observed at all, and returning 1.0 published a perfect score for a
    measurement that never happened — which made ``sprout calibrate --gate`` a
    merge-blocking step that passed on an empty probe file.
    """
    n = len(judge_labels)
    if n == 0:
        raise CalibrationError(
            "Cohen's kappa is undefined with no observations; a probe set that scores "
            "nothing has not been calibrated."
        )
    po = sum(1 for a, b in zip(judge_labels, human_labels, strict=True) if a == b) / n
    pj = sum(judge_labels) / n
    ph = sum(human_labels) / n
    pe = pj * ph + (1 - pj) * (1 - ph)
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def _decide(judge: Judge, probe: JudgeProbe) -> bool:
    if probe.kind == "entails":
        return judge.entails(probe.text_a, probe.sources).passed
    if probe.kind == "contains":
        return judge.contains(probe.text_a, probe.text_b).passed
    if probe.kind == "equivalent":
        return judge.equivalent(probe.text_a, probe.text_b).passed
    raise ValueError(f"unknown probe kind: {probe.kind}")


def calibrate(judge: Judge, probes: Sequence[JudgeProbe]) -> CalibrationRecord:
    """Run ``judge`` over labeled ``probes`` and compute agreement + kappa.

    Raises :class:`CalibrationError` when ``probes`` is empty. An empty probe set is a
    broken input, not a low score, and the difference matters: `sprout calibrate --gate`
    is a merge-blocking CI step, and a record over zero probes used to be built with
    ``agreement`` and ``cohens_kappa`` of ``1.0`` — so an empty or mis-keyed
    ``eval/judge_probes.yaml`` published "Raw agreement 1.000, κ 1.000, ✅ meets" and
    exited 0. Failing here is what makes the gate able to fail at all.
    """
    if not probes:
        raise CalibrationError(
            "no probes to calibrate against; a judge scored over zero labeled probes has "
            "not been calibrated, and reporting agreement or kappa for it would publish a "
            "number no observation supports."
        )
    judge_labels: list[bool] = []
    human_labels: list[bool] = []
    disagreements: list[str] = []
    by_op: dict[str, list[bool]] = {}
    for probe in probes:
        verdict = _decide(judge, probe)
        judge_labels.append(verdict)
        human_labels.append(probe.human_label)
        by_op.setdefault(probe.kind, []).append(verdict == probe.human_label)
        if verdict != probe.human_label:
            disagreements.append(probe.id)
    n = len(probes)
    n_agree = sum(1 for j, h in zip(judge_labels, human_labels, strict=True) if j == h)
    per_op = {
        op: OpAgreement(
            n=len(flags), n_agree=sum(flags), agreement=round(sum(flags) / len(flags), 4)
        )
        for op, flags in by_op.items()
    }
    return CalibrationRecord(
        judge_method=judge.method,
        judge_config_hash=judge.config_hash,
        n_probes=n,
        n_agree=n_agree,
        agreement=round(n_agree / n, 4),
        cohens_kappa=round(cohens_kappa(judge_labels, human_labels), 4),
        per_operation=per_op,
        disagreements=tuple(disagreements),
    )


def is_stale(record: CalibrationRecord, judge: Judge) -> bool:
    """True if the record was made for a different judge configuration."""
    return record.judge_config_hash != judge.config_hash


def to_markdown(record: CalibrationRecord) -> str:
    """Render a committed, human-facing calibration report."""
    ops = "\n".join(
        f"| {op} | {oa.n_agree}/{oa.n} | {oa.agreement:.2f} |"
        for op, oa in sorted(record.per_operation.items())
    )
    verdict = "✅ meets" if record.meets_threshold else "❌ below"
    # A record with no probes can only arrive here from committed JSON written before
    # `calibrate` refused to build one. Its stored 1.0s are an artifact of that bug, and
    # rendering them as figures would republish it, so they are named as unmeasured.
    measured = record.n_probes > 0
    agreement = f"**{record.agreement:.3f}**" if measured else "**not measured** (no probes)"
    kappa = f"**{record.cohens_kappa:.3f}**" if measured else "**not measured** (no probes)"
    return "\n".join(
        [
            "# Judge calibration report",
            "",
            f"**Judge:** `{record.judge_method}` (config `{record.judge_config_hash[:12]}`)",
            "",
            f"- Probes: {record.n_probes}",
            f"- Raw agreement with human labels: {agreement} (threshold {MIN_AGREEMENT})",
            f"- Cohen's κ: {kappa} (threshold {MIN_KAPPA}) — {verdict}",
            "",
            "| Operation | Agree | Agreement |",
            "|---|---|---|",
            ops,
            "",
            f"Disagreements: {', '.join(record.disagreements) or 'none'}",
            "",
            "> The deterministic lexical judge is the **reproducible offline floor**: lexical "
            "coverage plus a negation/antonym polarity guard, not a general-purpose semantic "
            "judge. It still misses morphological synonyms and paraphrase that share little "
            "surface vocabulary, which is why production gates should ultimately be backed by "
            "the calibrated LLM judge (`--judge llm`) as the probe set grows. Pass `--gate` to "
            "`sprout calibrate` to fail the build below threshold; run without it to report only.",
            "",
        ]
    )
