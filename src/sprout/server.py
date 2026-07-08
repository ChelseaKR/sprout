"""Accessible reference server: a small FastAPI app over the Assistant.

Endpoints: ``/livez`` (liveness, no deps), ``/readyz`` (index loaded), ``/health`` (index
size), ``/api/disclosure``, ``POST /api/chat`` (JSON), and ``GET /api/chat/stream`` (SSE).
The SSE stream is sentence-grained on purpose: each ``sentence`` event is already
citation-verified, so the live region never announces ungrounded text and then retracts it.
Handlers are sync ``def`` so FastAPI runs the synchronous pipeline in its threadpool.

CORS/TLS termination/proxy-level rate limiting are still expected from the deploy target's
reverse proxy, but per FIX-10 (``docs/ideation/02-large-scale-fixes.md``) the controls that
must hold even if that proxy is misconfigured or absent — security headers, a request-size
cap, per-IP rate limits, and a concurrency bound on the heaviest route — are app-level, wired
below via ``sprout.hardening``. See ``docs/audits/asvs-l2-delta.md`` for the ASVS L2 delta
this closes.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .answer import Assistant
from .config import Config
from .hardening import (
    ConcurrencyLimiter,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from .identify import PhotoCareService, PlantIdentifier, build_identifier
from .integrations import (
    FamilyGreenhouseRequest,
    canonical_payload,
    household_observations,
    selector_query,
    verify_signature,
)
from .models import Answer
from .obs import Logger
from .reminders import Reminder, ReminderError, ReminderStore

_FALLBACK_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "<title>Sprout</title></head><body><main><h1>Sprout 🌱</h1>"
    "<p>The bundled chat UI was not built. Use the JSON API at "
    '<code>POST /api/chat</code> or run <code>sprout ask "..."</code>.</p>'
    "</main></body></html>"
)


def _sse_events(answer: Answer) -> Iterator[dict[str, str]]:
    """Yield SSE events; every sentence emitted is already citation-verified."""
    if answer.refused:
        yield {"event": "refusal", "data": json.dumps({"text": answer.refusal_text or ""})}
    for sentence in answer.sentences:
        yield {
            "event": "sentence",
            "data": json.dumps(
                {
                    "text": sentence.text,
                    "citation": sentence.citation.label,
                    "url": sentence.citation.url,
                }
            ),
        }
    if answer.safety_notice:
        yield {"event": "safety", "data": json.dumps({"text": answer.safety_notice})}
    for notice in answer.disagreement_notices:
        yield {"event": "disagreement", "data": json.dumps({"text": notice})}
    yield {
        "event": "done",
        "data": json.dumps(
            {
                "refused": answer.refused,
                "low_confidence": answer.low_confidence,
                "confidence": answer.confidence,
                "language": answer.language,
                "as_of": answer.as_of,
                "disclosure": answer.disclosure,
            }
        ),
    }


def _register_health(app: FastAPI, engine: Assistant) -> None:
    @app.get("/livez")
    def livez() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        size = len(engine._store)
        ready = size > 0
        return JSONResponse(
            {"status": "ok" if ready else "no_index", "index_size": size},
            status_code=200 if ready else 503,
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "index_size": len(engine._store)}


def _register_hardening(app: FastAPI, config: Config) -> None:
    """Wire the FIX-10 app-level guards; see ``sprout.hardening`` for what each one does.

    Middleware is added innermost-first (Starlette wraps the *last*-added instance
    outermost), so security headers land on every response — including ones rejected by
    the size/rate-limit layers beneath them.
    """
    server = config.server
    app.add_middleware(
        RateLimitMiddleware,
        capacity=server.identify_rate_limit_requests,
        window_s=server.identify_rate_limit_window_s,
        path_prefix="/api/identify",
    )
    app.add_middleware(
        RateLimitMiddleware,
        capacity=server.rate_limit_requests,
        window_s=server.rate_limit_window_s,
        path_prefix="/api/",
    )
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=server.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware)


def _register_family_greenhouse(app: FastAPI, engine: Assistant, log: Logger) -> None:
    @app.post("/api/integrations/family-greenhouse/chat")
    async def family_greenhouse_chat(request: Request) -> JSONResponse:
        """First-party, read-only integration with minimized household context."""
        secret = os.environ.get("SPROUT_FAMILY_GREENHOUSE_SECRET", "")
        if not secret:
            return JSONResponse({"error": "integration is not configured"}, status_code=503)
        try:
            raw_body = await request.body()
            if len(raw_body) > 65_536:
                return JSONResponse({"error": "integration payload is too large"}, status_code=413)
            raw_payload = json.loads(raw_body)
            if not isinstance(raw_payload, dict):
                raise ValueError("payload must be an object")
            body = canonical_payload(raw_payload)
            timestamp = request.headers.get("x-sprout-timestamp", "")
            signature = request.headers.get("x-sprout-signature", "")
            if not verify_signature(secret, timestamp, body, signature):
                log.event("request_rejected")
                return JSONResponse({"error": "invalid integration signature"}, status_code=401)
            payload = FamilyGreenhouseRequest.model_validate(raw_payload)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            return JSONResponse(
                {"error": "invalid integration payload", "detail": str(exc)}, status_code=400
            )

        answer = engine.answer(selector_query(payload), payload.language)
        log.event(
            "answer",
            language=answer.language,
            refused=answer.refused,
            refusal_reason=answer.refusal_reason,
            is_safety_query=answer.is_safety_query,
            confidence=answer.confidence,
        )
        return JSONResponse(
            {
                "answer": {
                    "display_text": answer.display_text,
                    "citations": [citation.model_dump() for citation in answer.citations],
                    "safety_notice": answer.safety_notice,
                    "confidence": answer.confidence,
                    "low_confidence": answer.low_confidence,
                    "refused": answer.refused,
                    "as_of": answer.as_of,
                    "disclosure": answer.disclosure,
                    "language": answer.language,
                    "provenance": "corpus",
                },
                "household_observations": household_observations(payload),
                "context_policy": "household-data-selects-corpus-facts",
            }
        )


def _mount_ui(app: FastAPI) -> None:
    dist = Path("web/dist")
    if dist.is_dir() and (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")
    else:  # pragma: no cover - exercised only when the UI build is absent

        @app.get("/")
        def index() -> HTMLResponse:
            return HTMLResponse(_FALLBACK_HTML)


def create_app(
    config: Config,
    assistant: Assistant | None = None,
    identifier: PlantIdentifier | None = None,
) -> FastAPI:
    engine = assistant or Assistant.from_config(config)
    log = Logger(config.observability)
    app = FastAPI(title="Sprout", version="0.1.0")
    _register_hardening(app, config)

    def _resolve(question: str, language: str | None) -> Answer:
        answer = engine.answer(question, language)
        log.event(
            "answer",
            language=answer.language,
            refused=answer.refused,
            refusal_reason=answer.refusal_reason,
            is_safety_query=answer.is_safety_query,
            confidence=answer.confidence,
        )
        return answer

    _register_health(app, engine)
    _register_family_greenhouse(app, engine, log)

    @app.get("/api/disclosure")
    def disclosure(language: str = "en") -> dict[str, str]:
        return {"disclosure": config.prompts.disclosure_for(language)}

    @app.post("/api/chat")
    def chat(payload: dict[str, Any]) -> JSONResponse:
        question = str(payload.get("question", "")).strip()
        error = _question_error(question, config)
        if error is not None:
            log.event("request_rejected")
            return JSONResponse({"error": error}, status_code=400)
        answer = _resolve(question, payload.get("language"))
        data = answer.model_dump()
        data["display_text"] = answer.display_text
        data["citations"] = [c.model_dump() for c in answer.citations]
        return JSONResponse(data)

    @app.get("/api/chat/stream")
    def chat_stream(q: str, language: str | None = None) -> Any:
        from sse_starlette.sse import EventSourceResponse

        error = _question_error(q.strip(), config)
        if error is not None:
            return JSONResponse({"error": error}, status_code=400)
        return EventSourceResponse(_sse_events(_resolve(q.strip(), language)))

    _register_identify(app, engine, config, log, identifier)
    _register_reminders(app, config, log)
    _mount_ui(app)
    return app


def _register_identify(
    app: FastAPI,
    engine: Assistant,
    config: Config,
    log: Logger,
    identifier: PlantIdentifier | None = None,
) -> None:
    service = PhotoCareService(engine, identifier or build_identifier(config), config)
    concurrency = ConcurrencyLimiter(config.server.identify_max_concurrency)

    @app.post("/api/identify")
    def identify(payload: dict[str, Any]) -> JSONResponse:
        # Bounded worker concurrency (FIX-10): this route decodes and runs a vision call
        # over a large photo payload, so an unbounded burst can starve the threadpool the
        # rest of the API shares. Reject fast rather than queue behind a full pool.
        if not concurrency.try_acquire():
            return JSONResponse(
                {"error": "identify is at capacity, try again shortly"},
                status_code=503,
                headers={"Retry-After": "1"},
            )
        try:
            raw = str(payload.get("image_b64", ""))
            if not raw:
                return JSONResponse({"error": "image_b64 is required"}, status_code=400)
            try:
                image = base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError):
                return JSONResponse({"error": "image_b64 is not valid base64"}, status_code=400)
            raw_question = payload.get("question")
            # Coerce like /api/chat does: a non-string ``question`` (e.g. a number) must not
            # crash the language/answer pipeline with an unhandled 500.
            question = str(raw_question) if raw_question is not None else None
            result = service.identify_and_answer(
                image, question=question, language=payload.get("language")
            )
            log.event(
                "identify",
                status="identified" if result.identified else "fallback",
                refused=result.answer.refused if result.answer else None,
            )
            data: dict[str, Any] = {
                "identified": result.identified,
                "species_slug": result.species_slug,
                "display_name": result.display_name,
                "label": result.label,
                "message": result.message,
            }
            if result.identification is not None:
                data["identification"] = result.identification.model_dump()
            if result.answer is not None:
                ans = result.answer
                data["answer"] = {
                    "display_text": ans.display_text,
                    "citations": [c.model_dump() for c in ans.citations],
                    "safety_notice": ans.safety_notice,
                    "confidence": ans.confidence,
                    "low_confidence": ans.low_confidence,
                    "as_of": ans.as_of,
                    "disclosure": ans.disclosure,
                    "language": ans.language,
                    "disagreements": [d.model_dump() for d in ans.disagreements],
                }
            return JSONResponse(data)
        finally:
            concurrency.release()


def _reminder_dump(r: Reminder) -> dict[str, Any]:
    return r.model_dump()


def _register_reminders(app: FastAPI, config: Config, log: Logger) -> None:
    def _store() -> ReminderStore:
        return ReminderStore(config.reminders.path, max_reminders=config.reminders.max_reminders)

    @app.get("/api/reminders")
    def list_reminders() -> JSONResponse:
        return JSONResponse({"reminders": [_reminder_dump(r) for r in _store().all_reminders()]})

    @app.get("/api/reminders/due")
    def due_reminders() -> JSONResponse:
        return JSONResponse({"reminders": [_reminder_dump(r) for r in _store().due()]})

    @app.post("/api/reminders")
    def create_reminder(payload: dict[str, Any]) -> JSONResponse:
        plant = str(payload.get("plant", "")).strip()
        kind = str(payload.get("kind", "water"))
        if not plant:
            return JSONResponse({"error": "plant is required"}, status_code=400)
        supplied_interval = payload.get("interval_days")
        interval = (
            config.reminders.default_intervals.get(kind, 7)
            if supplied_interval is None
            else supplied_interval
        )
        try:
            reminder = _store().add(
                plant=plant,
                kind=kind,  # type: ignore[arg-type]
                interval_days=int(interval),
                language=str(payload.get("language", "en")),
                note=str(payload.get("note", "")),
                source=payload.get("source"),
            )
        except (ReminderError, TypeError, ValueError) as exc:
            # TypeError: a non-numeric ``interval_days`` (e.g. a list) must be a 400,
            # not an unhandled 500.
            return JSONResponse({"error": str(exc)}, status_code=400)
        log.event("reminder_added", status="ok")
        return JSONResponse(_reminder_dump(reminder), status_code=201)

    @app.post("/api/reminders/{reminder_id}/complete")
    def complete_reminder(reminder_id: str) -> JSONResponse:
        try:
            reminder = _store().complete(reminder_id)
        except ReminderError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return JSONResponse(_reminder_dump(reminder))

    @app.delete("/api/reminders/{reminder_id}")
    def delete_reminder(reminder_id: str) -> JSONResponse:
        removed = _store().remove(reminder_id)
        return JSONResponse({"removed": removed}, status_code=200 if removed else 404)


def _question_error(question: str, config: Config) -> str | None:
    if not question:
        return "question must not be empty"
    if len(question) > config.server.max_question_chars:
        return f"question exceeds {config.server.max_question_chars} characters"
    return None
