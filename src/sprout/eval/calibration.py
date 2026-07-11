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
        return self.agreement >= MIN_AGREEMENT and self.cohens_kappa >= MIN_KAPPA


def cohens_kappa(judge_labels: Sequence[bool], human_labels: Sequence[bool]) -> float:
    """Cohen's kappa for two binary label sequences. Degenerate expected-agreement -> 1.0."""
    n = len(judge_labels)
    if n == 0:
        return 1.0
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
    """Run ``judge`` over labeled ``probes`` and compute agreement + kappa."""
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
        agreement=round(n_agree / n, 4) if n else 1.0,
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
    return "\n".join(
        [
            "# Judge calibration report",
            "",
            f"**Judge:** `{record.judge_method}` (config `{record.judge_config_hash[:12]}`)",
            "",
            f"- Probes: {record.n_probes}",
            f"- Raw agreement with human labels: **{record.agreement:.3f}** "
            f"(threshold {MIN_AGREEMENT})",
            f"- Cohen's κ: **{record.cohens_kappa:.3f}** (threshold {MIN_KAPPA}) — {verdict}",
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
