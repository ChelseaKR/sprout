"""Tier-A OTel wiring: no-op posture for tier B/C, real RED metrics + span attributes +
trace propagation for tier A, and log/trace correlation. Uses OTel's own in-memory
exporter/reader (never real network) so these are fast, hermetic unit tests, not
integration tests against a live Collector.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator, MutableMapping, Sequence
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import HistogramDataPoint, InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sprout.config import ObservabilityConfig
from sprout.obs import Logger
from sprout.otel import ObservabilityHandles, REDMiddleware, configure_observability

Handles = tuple[ObservabilityHandles, InMemorySpanExporter, InMemoryMetricReader]


@pytest.fixture
def handles() -> Iterator[Handles]:
    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    h = configure_observability(
        ObservabilityConfig(tier="A"),
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )
    assert h is not None
    yield h, span_exporter, metric_reader
    h.shutdown()


def _app_with_middleware(handles: ObservabilityHandles) -> FastAPI:
    app = FastAPI()
    app.add_middleware(REDMiddleware, handles=handles)

    @app.get("/api/items/{item_id}")
    def get_item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    @app.get("/boom")
    def boom() -> None:
        raise ValueError("kaboom")

    return app


def test_configure_observability_noop_for_tier_b_and_c() -> None:
    assert configure_observability(ObservabilityConfig(tier="C")) is None
    assert configure_observability(ObservabilityConfig(tier="B")) is None


def test_configure_observability_returns_handles_for_tier_a(handles: Handles) -> None:
    h, _, _ = handles
    assert h.tracer is not None
    assert h.requests_total is not None
    assert h.duration_seconds is not None
    assert h.errors_total is not None


def _metric_points(metric_reader: InMemoryMetricReader, name: str) -> list[dict[str, Any]]:
    data = metric_reader.get_metrics_data()
    points: list[dict[str, Any]] = []
    if data is None:
        return points
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == name:
                    points.extend(dict(dp.attributes or {}) for dp in metric.data.data_points)
    return points


def test_red_middleware_records_requests_and_duration_by_route_template(
    handles: Handles,
) -> None:
    h, _span_exporter, metric_reader = handles
    client = TestClient(_app_with_middleware(h))

    client.get("/api/items/42")
    client.get("/api/items/other")

    requests = _metric_points(metric_reader, "sprout_http_requests_total")
    assert {"method": "GET", "route": "/api/items/{item_id}", "status_code": "200"} in requests

    durations = _metric_points(metric_reader, "sprout_http_request_duration_seconds")
    assert {"method": "GET", "route": "/api/items/{item_id}"} in durations


def test_red_middleware_labels_unmatched_paths_not_raw_path(handles: Handles) -> None:
    """A probe/scan hitting arbitrary unmatched paths must not blow up the route label's
    cardinality — every 404 collapses to a single ``"unmatched"`` label value."""
    h, _, metric_reader = handles
    client = TestClient(_app_with_middleware(h))

    client.get("/this-path-does-not-exist")
    client.get("/neither/does/this/one")

    requests = _metric_points(metric_reader, "sprout_http_requests_total")
    unmatched = [r for r in requests if r["route"] == "unmatched"]
    assert unmatched
    assert all(r["status_code"] == "404" for r in unmatched)
    # never the raw, unbounded path
    assert not any("does-not-exist" in str(r) or "neither" in str(r) for r in requests)


def test_red_middleware_records_errors_on_unhandled_exception(handles: Handles) -> None:
    h, _, metric_reader = handles
    client = TestClient(_app_with_middleware(h), raise_server_exceptions=False)

    resp = client.get("/boom")
    assert resp.status_code == 500

    errors = _metric_points(metric_reader, "sprout_http_request_errors_total")
    assert {"method": "GET", "route": "/boom", "error_type": "ValueError"} in errors


def test_red_middleware_duration_buckets_match_the_observability_standard(
    handles: Handles,
) -> None:
    """STANDARDS/OBSERVABILITY-STANDARD.md §2's fixed bucket list, in seconds — not the
    OTel SDK's millisecond-shaped default."""
    h, _, metric_reader = handles
    client = TestClient(_app_with_middleware(h))
    client.get("/api/items/1")

    data = metric_reader.get_metrics_data()
    assert data is not None
    bounds: Sequence[float] | None = None
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == "sprout_http_request_duration_seconds":
                    point = metric.data.data_points[0]
                    assert isinstance(point, HistogramDataPoint)
                    bounds = point.explicit_bounds
    assert bounds == (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def test_red_middleware_span_carries_semconv_http_attributes(handles: Handles) -> None:
    h, span_exporter, _ = handles
    client = TestClient(_app_with_middleware(h))
    client.get("/api/items/7")
    h._tracer_provider.force_flush()

    spans = span_exporter.get_finished_spans()
    assert spans
    span = spans[0]
    assert span.attributes is not None
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["http.route"] == "/api/items/{item_id}"
    assert span.attributes["http.response.status_code"] == 200


def test_red_middleware_propagates_incoming_traceparent(handles: Handles) -> None:
    """A W3C traceparent on the inbound request becomes the span's trace id
    (STANDARDS/OBSERVABILITY-STANDARD.md §1)."""
    h, span_exporter, _ = handles
    client = TestClient(_app_with_middleware(h))
    incoming_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    client.get(
        "/api/items/1",
        headers={"traceparent": f"00-{incoming_trace_id}-00f067aa0ba902b7-01"},
    )
    h._tracer_provider.force_flush()

    spans = span_exporter.get_finished_spans()
    assert spans
    assert format(spans[0].context.trace_id, "032x") == incoming_trace_id


def test_json_logs_carry_trace_correlation_for_tier_a(handles: Handles) -> None:
    """STANDARDS/OBSERVABILITY-STANDARD.md §3: every Tier-A JSON log record carries
    trace_id/span_id of the active span."""
    h, _, _ = handles
    buf = io.StringIO()
    log = Logger(ObservabilityConfig(log_format="json", tier="A"), stream=buf)

    with h.tracer.start_as_current_span("test-span") as span:
        expected_trace_id = format(span.get_span_context().trace_id, "032x")
        log.event("answer", language="en")

    record = json.loads(buf.getvalue().strip())
    assert record["trace_id"] == expected_trace_id
    assert "span_id" in record


def test_json_logs_have_no_trace_fields_outside_an_active_span_or_tier(
    handles: Handles,
) -> None:
    buf = io.StringIO()
    log = Logger(ObservabilityConfig(log_format="json", tier="A"), stream=buf)
    log.event("answer", language="en")  # no active span
    record = json.loads(buf.getvalue().strip())
    assert "trace_id" not in record

    buf_c = io.StringIO()
    Logger(ObservabilityConfig(log_format="json", tier="C"), stream=buf_c).event(
        "answer", language="en"
    )
    record_c = json.loads(buf_c.getvalue().strip())
    assert "trace_id" not in record_c


def test_red_middleware_passes_through_non_http_scopes(handles: Handles) -> None:
    """Lifespan/websocket ASGI scopes are not HTTP requests and get no span/metrics —
    the middleware must still forward them to the inner app untouched."""
    h, _, _ = handles
    events: list[str] = []

    async def _inner_app(scope: Any, receive: Any, send: Any) -> None:
        events.append(scope["type"])

    middleware = REDMiddleware(_inner_app, h)

    import asyncio

    asyncio.run(middleware({"type": "lifespan"}, _noop_receive, _noop_send))
    assert events == ["lifespan"]


async def _noop_receive() -> MutableMapping[str, Any]:
    return {}


async def _noop_send(message: MutableMapping[str, Any]) -> None:
    return None


def test_configure_observability_returns_none_when_extra_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``observability.tier: A`` is set but the ``observability`` extra was never
    installed, the server must still start — no-op instrumentation, not a crash."""
    import builtins

    real_import = builtins.__import__

    def _blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError(f"simulated missing dependency: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    assert configure_observability(ObservabilityConfig(tier="A")) is None


def test_log_trace_context_degrades_when_extra_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """`obs._trace_context` must degrade the same way `otel.configure_observability`
    does: no crash, just no trace fields, if the `observability` extra vanished."""
    import builtins

    real_import = builtins.__import__

    def _blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError(f"simulated missing dependency: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    buf = io.StringIO()
    Logger(ObservabilityConfig(log_format="json", tier="A"), stream=buf).event(
        "answer", language="en"
    )
    record = json.loads(buf.getvalue().strip())
    assert "trace_id" not in record
