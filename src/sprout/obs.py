"""Structured, PII-free operational logging.

Tier C (the offline CLI) logs human-readable text by default and structured JSON when
``observability.log_format: json`` is selected; the optional server surface is Tier A. The
logger is PII-free *by construction*: callers pass only whitelisted, low-cardinality fields
(event name, language, refusal reason, counts) — never the user's question text. A clock is
injectable so tests are deterministic.

For Tier A (``observability.tier: "A"``), every JSON record also carries ``trace_id`` /
``span_id`` / ``trace_flags`` of the currently active OTel span, per
``STANDARDS/OBSERVABILITY-STANDARD.md`` §3 ("every Tier-A log record MUST contain ...
trace_id, span_id"). These are infrastructure metadata, like ``ts``/``service.name``, not
caller-supplied fields — they are never filtered through ``_ALLOWED_FIELDS`` and never
carry request content. Absent for Tier B/C, and absent (never raising) when no span is
active or the ``observability`` extra is not installed.
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
        # An exception's *class name* only (see ``server._error_kind``) — never its
        # message, which is free text that echoes caller input. Handlers that used to
        # return ``str(exc)`` to the client log this instead.
        "error_kind",
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
            record: dict[str, Any] = {
                "ts": self._clock(),
                "severity": "INFO",
                "service.name": self._config.service_name,
                "event": name,
                **_trace_context(self._config),
                **safe,
            }
            line = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            print(line, file=self._stream)
        else:
            extras = " ".join(f"{k}={v}" for k, v in sorted(safe.items()))
            print(f"[{self._config.service_name}] {name} {extras}".rstrip(), file=self._stream)


def _trace_context(config: ObservabilityConfig) -> dict[str, str]:
    """Tier A only: trace_id/span_id/trace_flags of the current OTel span, for the
    log-trace correlation ``STANDARDS/OBSERVABILITY-STANDARD.md`` §3 requires. Returns
    ``{}`` for Tier B/C, when no span is active, or when the ``observability`` extra is
    not installed — this never raises, so a telemetry outage never breaks logging."""
    if config.tier != "A":
        return {}
    try:
        from opentelemetry import trace
    except ImportError:
        return {}
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return {}
    return {
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
        "trace_flags": format(ctx.trace_flags, "02x"),
    }
