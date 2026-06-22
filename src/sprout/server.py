"""Accessible chat server: a small FastAPI app over the Assistant.

Endpoints: ``/livez`` (liveness, no deps), ``/readyz`` (index loaded), ``/health`` (index
size), ``/api/disclosure``, ``POST /api/chat`` (JSON), and ``GET /api/chat/stream`` (SSE).
The SSE stream is sentence-grained on purpose: each ``sentence`` event is already
citation-verified, so the live region never announces ungrounded text and then retracts it.
Handlers are sync ``def`` so FastAPI runs the synchronous pipeline in its threadpool;
rate-limiting/CORS/auth are left to the proxy layer.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .answer import Assistant
from .config import Config
from .models import Answer
from .obs import Logger

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
        ready = len(engine._store) > 0
        return JSONResponse(
            {"status": "ok" if ready else "no_index", "index_size": len(engine._store)},
            status_code=200 if ready else 503,
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "index_size": len(engine._store)}


def _mount_ui(app: FastAPI) -> None:
    dist = Path("web/dist")
    if dist.is_dir() and (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")
    else:  # pragma: no cover - exercised only when the UI build is absent

        @app.get("/")
        def index() -> HTMLResponse:
            return HTMLResponse(_FALLBACK_HTML)


def create_app(config: Config, assistant: Assistant | None = None) -> FastAPI:
    engine = assistant or Assistant.from_config(config)
    log = Logger(config.observability)
    app = FastAPI(title="Sprout", version="0.1.0")

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

    _mount_ui(app)
    return app


def _question_error(question: str, config: Config) -> str | None:
    if not question:
        return "question must not be empty"
    if len(question) > config.server.max_question_chars:
        return f"question exceeds {config.server.max_question_chars} characters"
    return None
