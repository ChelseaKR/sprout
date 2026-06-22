"""Judges: the single model-touching seam, behind one Protocol.

A suite splits an answer into claims and asks a ``Judge`` three relational questions —
``entails`` (groundedness), ``contains`` (fact/anchor coverage), ``equivalent``
(multilingual). Because that is the only place a model is consulted, a suite is identical
whether it runs under the offline ``DeterministicJudge`` (lexical coverage + a negation
polarity guard, fully reproducible, no network) or an LLM judge. The judge's ``config_hash``
is folded into the run fingerprint, so any judge/model/threshold change is visible in the
run identity — and a calibration record is invalidated when it changes.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from ..determinism import sha256_of_obj
from ..text import coverage, has_negation, jaccard, split_sentences


class JudgeDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float
    passed: bool
    detail: str = ""


@runtime_checkable
class Judge(Protocol):
    method: str
    config: dict[str, Any]

    @property
    def config_hash(self) -> str: ...

    def entails(self, claim: str, sources: list[str]) -> JudgeDecision: ...

    def contains(self, answer: str, fact: str) -> JudgeDecision: ...

    def equivalent(self, a: str, b: str) -> JudgeDecision: ...


class DeterministicJudge:
    """Crude by design: lexical coverage + polarity guard. Auditable and reproducible."""

    method = "deterministic-lexical"

    def __init__(
        self,
        entail_threshold: float = 0.6,
        contains_threshold: float = 0.6,
        equivalence_threshold: float = 0.5,
    ) -> None:
        self.config: dict[str, Any] = {
            "method": self.method,
            "version": "1.0.0",
            "entail_threshold": entail_threshold,
            "contains_threshold": contains_threshold,
            "equivalence_threshold": equivalence_threshold,
        }

    @property
    def config_hash(self) -> str:
        return sha256_of_obj(self.config)

    def entails(self, claim: str, sources: list[str]) -> JudgeDecision:
        if not sources:
            return JudgeDecision(score=0.0, passed=False, detail="no sources")
        # Compare polarity against the best-matching source SENTENCE, not the whole
        # passage: a multi-sentence source can carry a negation in an unrelated sentence,
        # which would otherwise falsely flag a verbatim-grounded claim as a contradiction.
        candidates = [s for src in sources for s in split_sentences(src)] or list(sources)
        scored = [(coverage(claim, s), s) for s in candidates]
        best_cov, best_sentence = max(scored, key=lambda t: t[0])
        polarity_ok = has_negation(claim) == has_negation(best_sentence)
        threshold = float(self.config["entail_threshold"])
        passed = best_cov >= threshold and polarity_ok
        detail = (
            f"coverage={best_cov:.2f}"
            if polarity_ok
            else f"coverage={best_cov:.2f} but negation polarity differs (contradiction)"
        )
        return JudgeDecision(score=round(best_cov, 4), passed=passed, detail=detail)

    def contains(self, answer: str, fact: str) -> JudgeDecision:
        cov = coverage(fact, answer)
        threshold = float(self.config["contains_threshold"])
        return JudgeDecision(
            score=round(cov, 4), passed=cov >= threshold, detail=f"coverage={cov:.2f}"
        )

    def equivalent(self, a: str, b: str) -> JudgeDecision:
        sim = jaccard(a, b)
        threshold = float(self.config["equivalence_threshold"])
        return JudgeDecision(
            score=round(sim, 4), passed=sim >= threshold, detail=f"jaccard={sim:.2f}"
        )


def build_judge(name: str, *, completion: Any = None) -> Judge:
    """Resolve a judge by name. ``deterministic`` is offline; ``llm``/``anthropic`` need a key."""
    if name == "deterministic":
        return DeterministicJudge()
    if name in ("llm", "anthropic"):
        from .llm_judge import AnthropicJudge

        return AnthropicJudge(completion=completion)
    raise ValueError(f"unknown judge: {name}")  # pragma: no cover - defensive
