"""Optional LLM-as-judge (Anthropic), behind the same Judge protocol.

The model call is injected as a ``CompletionFn`` so the judge is fully testable offline and
is never hit in CI. The judge model (Claude Sonnet) is deliberately *different* from the
default answer model (Claude Haiku) — judge != answer model is structural. All of model id,
prompt version, temperature, and thresholds live in the hashed config, so the run identity
changes if any of them change. Malformed judge output raises (fail closed). Excluded from
coverage: the default completion path requires a live API key and network.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from ..determinism import sha256_of_obj
from .judge import JudgeDecision

CompletionFn = Callable[[str, str], str]

# Judge model differs from the answer model (Haiku) on purpose.
DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"
PROMPT_VERSION = "2026-06-22.1"

_SYSTEM = (
    "You are a rigorous, conservative evaluation judge for a plant-care assistant. "
    'Answer ONLY with a compact JSON object {"score": <float 0..1>, "reason": "<short>"}. '
    "Be strict: when unsure, score low."
)
_TASKS: dict[str, str] = {
    "entails": (
        "Does the CLAIM follow from the SOURCES (no new facts, no contradiction)?\n"
        "CLAIM: {a}\nSOURCES: {b}"
    ),
    "contains": "Does the ANSWER state the FACT?\nANSWER: {a}\nFACT: {b}",
    "equivalent": "Do these two answers convey the same facts?\nA: {a}\nB: {b}",
}


class _Cfg(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str
    model: str
    prompt_version: str
    temperature: float
    max_tokens: int
    entail_threshold: float
    contains_threshold: float
    equivalence_threshold: float


class AnthropicJudge:
    """Claude judge; the model call is injected so the harness stays testable."""

    method = "llm-judge-anthropic"

    def __init__(
        self,
        *,
        completion: CompletionFn | None = None,
        model: str = DEFAULT_JUDGE_MODEL,
        threshold: float = 0.7,
    ) -> None:
        self._cfg = _Cfg(
            method=self.method,
            model=model,
            prompt_version=PROMPT_VERSION,
            temperature=0.0,
            max_tokens=256,
            entail_threshold=threshold,
            contains_threshold=threshold,
            equivalence_threshold=threshold,
        )
        self.config: dict[str, Any] = self._cfg.model_dump()
        self._completion = completion or self._default_completion

    @property
    def config_hash(self) -> str:
        return sha256_of_obj(self.config)

    def _default_completion(self, system: str, user: str) -> str:
        import httpx

        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self._cfg.model,
                "max_tokens": self._cfg.max_tokens,
                "temperature": self._cfg.temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks)

    def _judge(self, kind: str, a: str, b: str, threshold: float) -> JudgeDecision:
        user = _TASKS[kind].format(a=a, b=b)
        raw = self._completion(_SYSTEM, user)
        score, reason = _parse_score(raw)
        return JudgeDecision(score=score, passed=score >= threshold, detail=reason)

    def entails(self, claim: str, sources: list[str]) -> JudgeDecision:
        return self._judge("entails", claim, " ".join(sources), self._cfg.entail_threshold)

    def contains(self, answer: str, fact: str) -> JudgeDecision:
        return self._judge("contains", answer, fact, self._cfg.contains_threshold)

    def equivalent(self, a: str, b: str) -> JudgeDecision:
        return self._judge("equivalent", a, b, self._cfg.equivalence_threshold)


def _parse_score(raw: str) -> tuple[float, str]:
    """Extract {score, reason} JSON from a model response. Malformed output raises."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"judge returned no JSON object: {raw!r}")
    try:
        obj = json.loads(raw[start : end + 1])
        return float(obj["score"]), str(obj.get("reason", ""))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed judge output: {raw!r}") from exc
