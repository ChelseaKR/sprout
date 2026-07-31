"""OpenTelemetry wiring for the Tier-A serverless API surface (opt-in).

Wires OTel traces + metrics — RED (rate/errors/duration) per endpoint — behind
``observability.tier: A``, per ``STANDARDS/OBSERVABILITY-STANDARD.md`` §§1-2. The
``opentelemetry-*`` packages are an optional extra (``pip install sprout[observability]``):
every import in this module is lazy and guarded, so a Tier-C (offline CLI) install never
needs them, and a Tier-A deploy that forgot the extra degrades to no-op instrumentation
rather than crashing the server — the same never-crash-on-a-missing-optional-provider
posture as ``providers/bedrock.py``.

Exporter endpoint/protocol come from the standard ``OTEL_EXPORTER_OTLP_*`` environment
variables (never from ``config/sprout.yaml`` — the standard puts exporter wiring in the
container manifest, not code; see ``infra/sprout_stack.py``).

Metric names follow the standard's Prometheus convention (``<service>_http_*``, base
units, ``_total`` on counters): ``sprout_http_requests_total``,
``sprout_http_request_duration_seconds``, ``sprout_http_request_errors_total``. Labels are
``method``, ``route`` (the *matched route template*, e.g. ``/api/reminders/{reminder_id}``
— never the raw path, which is unbounded cardinality) and ``status_code``/``error_type``.
No label ever carries a user id, question text, or any other unbounded/PII value, matching
the cardinality rule in ``STANDARDS/OBSERVABILITY-STANDARD.md`` §2.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from typing import Any

from .config import ObservabilityConfig

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

_UNMATCHED_ROUTE = "unmatched"

# STANDARDS/OBSERVABILITY-STANDARD.md §2's fixed RED histogram buckets, in seconds. The
# OTel SDK's own default histogram boundaries are millisecond-shaped and do not match this
# standard, so the duration histogram gets an explicit View pinning these.
_DURATION_BUCKETS_S = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


@dataclass
class ObservabilityHandles:
    """Live OTel providers + the three RED instruments for one process."""

    tracer: Any
    requests_total: Any
    duration_seconds: Any
    errors_total: Any
    _tracer_provider: Any
    _meter_provider: Any

    def shutdown(self) -> None:
        """Flush and stop both providers. Call once, on process/app shutdown."""
        self._tracer_provider.shutdown()
        self._meter_provider.shutdown()


def configure_observability(
    config: ObservabilityConfig,
    *,
    span_exporter: Any | None = None,
    metric_reader: Any | None = None,
) -> ObservabilityHandles | None:
    """Set up OTel tracing + metrics for Tier A. Returns ``None`` (no-op) for Tier B/C,
    or for Tier A when the ``observability`` extra is not installed.

    ``span_exporter``/``metric_reader`` are injectable (tests pass an in-memory exporter
    so they never touch the network); production leaves them unset and gets the real
    OTLP-over-HTTP exporters, endpoint/protocol read from ``OTEL_EXPORTER_OTLP_*`` env.

    The returned ``tracer``/instruments are bound to *this call's* local provider
    objects (``tracer_provider.get_tracer(...)``, not the bare ``trace.get_tracer(...)``
    global-API call) — the global providers are also registered, for the benefit of any
    future auto-instrumented library, but a second registration in the same process is a
    silent no-op per the OTel API, and this way our own spans/metrics and ``shutdown()``
    always refer to the provider this function actually built, never a stale global one.
    """
    if config.tier != "A":
        return None
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return None

    resource = Resource.create(
        {
            "service.name": config.service_name,
            "service.version": config.service_version,
            "deployment.environment": config.deployment_environment,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(span_exporter if span_exporter is not None else OTLPSpanExporter())
    )
    trace.set_tracer_provider(tracer_provider)
    tracer = tracer_provider.get_tracer(config.service_name, config.service_version)

    reader = (
        metric_reader
        if metric_reader is not None
        else PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=60_000)
    )
    prefix = config.service_name
    duration_view = View(
        instrument_name=f"{prefix}_http_request_duration_seconds",
        aggregation=ExplicitBucketHistogramAggregation(boundaries=_DURATION_BUCKETS_S),
    )
    meter_provider = MeterProvider(
        resource=resource, metric_readers=[reader], views=[duration_view]
    )
    metrics.set_meter_provider(meter_provider)
    meter = meter_provider.get_meter(config.service_name, config.service_version)

    requests_total = meter.create_counter(
        f"{prefix}_http_requests_total",
        unit="1",
        description="Count of HTTP requests, labeled method/route/status_code.",
    )
    duration_seconds = meter.create_histogram(
        f"{prefix}_http_request_duration_seconds",
        unit="s",
        description="HTTP request duration, labeled method/route.",
    )
    errors_total = meter.create_counter(
        f"{prefix}_http_request_errors_total",
        unit="1",
        description=(
            "Count of HTTP requests that errored (5xx or unhandled exception), "
            "labeled method/route/error_type."
        ),
    )
    return ObservabilityHandles(
        tracer=tracer,
        requests_total=requests_total,
        duration_seconds=duration_seconds,
        errors_total=errors_total,
        _tracer_provider=tracer_provider,
        _meter_provider=meter_provider,
    )


class REDMiddleware:
    """Pure-ASGI middleware: one span plus the three RED instruments per HTTP request.

    A raw ASGI middleware (not ``BaseHTTPMiddleware``) so it shares the mutable ``scope``
    dict with the router underneath it: after awaiting the inner app, Starlette has
    already set ``scope["route"]`` to the *matched route object*, so the metric/span
    ``route`` label is the template (``/api/reminders/{reminder_id}``), not the raw path —
    an unmatched request (404) is labeled ``"unmatched"`` rather than the raw path, so a
    scan/probe storm can't blow up label cardinality.
    """

    def __init__(self, app: Any, handles: ObservabilityHandles) -> None:
        self._app = app
        self._handles = handles

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        from opentelemetry import context as otel_context
        from opentelemetry import propagate, trace
        from opentelemetry.trace import SpanKind, Status, StatusCode

        method = str(scope.get("method", "GET"))
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        parent_ctx = propagate.extract(headers)
        token = otel_context.attach(parent_ctx)

        status_code = 500

        async def _send(message: MutableMapping[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        span = self._handles.tracer.start_span(
            f"{method} {scope.get('path', '')}", context=parent_ctx, kind=SpanKind.SERVER
        )
        start = time.perf_counter()
        error_type: str | None = None
        try:
            with trace.use_span(span, end_on_exit=False):
                await self._app(scope, receive, _send)
        except Exception as exc:
            error_type = type(exc).__name__
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            duration = time.perf_counter() - start
            route = scope.get("route")
            route_path = getattr(route, "path", None) or _UNMATCHED_ROUTE

            span.set_attribute("http.request.method", method)
            span.set_attribute("http.route", route_path)
            span.set_attribute("url.path", str(scope.get("path", "")))
            span.set_attribute("url.scheme", str(scope.get("scheme", "http")))
            span.set_attribute("http.response.status_code", status_code)
            if status_code >= 500 or error_type is not None:
                span.set_attribute("error.type", error_type or f"http_{status_code}")
            span.end()
            otel_context.detach(token)

            labels = {"method": method, "route": route_path}
            self._handles.requests_total.add(1, {**labels, "status_code": str(status_code)})
            self._handles.duration_seconds.record(duration, labels)
            if status_code >= 500 or error_type is not None:
                self._handles.errors_total.add(
                    1, {**labels, "error_type": error_type or f"http_{status_code}"}
                )
