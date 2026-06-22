"""Structured, PII-free operational logging.

Tier C (the offline CLI) logs human-readable text by default and structured JSON when
``observability.log_format: json`` is selected; the optional server surface is Tier A. The
logger is PII-free *by construction*: callers pass only whitelisted, low-cardinality fields
(event name, language, refusal reason, counts) — never the user's question text. A clock is
injectable so tests are deterministic.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any, TextIO

from .config import ObservabilityConfig

# Fields that may carry free text are never logged; these are the only allowed keys.
_ALLOWED_FIELDS = frozenset(
    {
        "language",
        "refused",
        "refusal_reason",
        "is_safety_query",
        "confidence",
        "low_confidence",
        "n_retrieved",
        "n_sentences",
        "injection_categories",
        "status",
        "route",
        "index_size",
    }
)


class Logger:
    """Emits one JSON object (or one text line) per event, PII-free."""

    def __init__(
        self,
        config: ObservabilityConfig | None = None,
        *,
        stream: TextIO | None = None,
        clock: Callable[[], str] = lambda: "",
    ) -> None:
        self._config = config or ObservabilityConfig()
        self._stream = stream if stream is not None else sys.stderr
        self._clock = clock

    def event(self, name: str, **fields: Any) -> None:
        safe = {k: v for k, v in fields.items() if k in _ALLOWED_FIELDS}
        if self._config.log_format == "json":
            record = {
                "ts": self._clock(),
                "severity": "INFO",
                "service.name": self._config.service_name,
                "event": name,
                **safe,
            }
            line = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            print(line, file=self._stream)
        else:
            extras = " ".join(f"{k}={v}" for k, v in sorted(safe.items()))
            print(f"[{self._config.service_name}] {name} {extras}".rstrip(), file=self._stream)
