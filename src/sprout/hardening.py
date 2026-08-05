"""Deploy-grade server hardening (FIX-10, `docs/ideation/02-large-scale-fixes.md`).

`server.py` used to say "rate-limiting/CORS/auth are left to the proxy layer" — true for the
offline default, but not once the UI sits behind a real URL: an unauthenticated
`/api/identify` accepting multi-megabyte bodies with no proxy-independent guard is exactly
the ASVS L2 gap RESEARCH-ROADMAP R4 (deploy the UI) opens. The middleware here holds even if
the reverse proxy in front of it is misconfigured or absent, per the delta checklist at
`docs/audits/asvs-l2-delta.md`.

Every guard is pure-stdlib (no new runtime dependency) and lives entirely on the `serve`
path — `sprout.cli` never imports this module, so the offline, zero-dependency mode
(ADR-0008) is untouched.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# Conservative, framework-free defaults for a single-page chat app with no third-party
# embeds: same-origin everything, no inline script/style, no framing.
SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    # Inert over plain HTTP (e.g. a local dev proxy); takes effect once served over TLS.
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}


async def _reject(
    send: Send, status: int, detail: str, extra_headers: list[tuple[bytes, bytes]] | None = None
) -> None:
    body = json.dumps({"error": detail}).encode("utf-8")
    headers = [(b"content-type", b"application/json")]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class SecurityHeadersMiddleware:
    """Adds the CSP/HSTS/anti-sniffing/anti-framing header set to every response.

    Wraps every downstream middleware's `send`, so headers land on rejected requests
    (413/429) as well as normal responses — register this one last (outermost).
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {name.decode("latin-1").lower() for name, _ in headers}
                for name, value in SECURITY_HEADERS.items():
                    if name.lower() not in existing:
                        headers.append((name.encode("latin-1"), value.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, _send)


class _PayloadTooLarge(Exception):
    pass


class RequestSizeLimitMiddleware:
    """Rejects request bodies over `max_bytes`, independent of any proxy body-size cap.

    Checks `Content-Length` up front for the common case, and also counts bytes as the
    body streams in so a chunked request with no declared length cannot bypass the cap.
    The `/api/identify` route is the reason this exists: an 8 MB photo, base64-inflated
    ~1.33x plus JSON overhead, is a real, unbounded-today payload.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self._max_bytes:
                    await _reject(send, 413, "request body exceeds the size limit")
                    return
            except ValueError:
                pass  # malformed header; fall through to the streaming counter

        seen = 0

        async def _counted_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message.get("type") == "http.request":
                seen += len(message.get("body") or b"")
                if seen > self._max_bytes:
                    raise _PayloadTooLarge()
            return message

        try:
            await self._app(scope, _counted_receive, send)
        except _PayloadTooLarge:
            await _reject(send, 413, "request body exceeds the size limit")


class _TokenBucket:
    """A simple, thread-safe token bucket: `capacity` requests per `window_s` seconds."""

    __slots__ = ("capacity", "lock", "refill_per_s", "tokens", "updated")

    def __init__(self, capacity: int, window_s: float) -> None:
        self.capacity = float(capacity)
        self.refill_per_s = capacity / window_s
        self.tokens = float(capacity)
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill_per_s)
            self.updated = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


class RateLimitMiddleware:
    """Per-client-IP token-bucket rate limiting, applied without relying on a proxy.

    Buckets are process-local and in-memory: correct for a single reference instance,
    documented as a known limitation for multi-instance deployment in
    `docs/audits/asvs-l2-delta.md` (a shared store is the fix, not in scope here).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        capacity: int,
        window_s: float,
        path_prefix: str = "",
        max_tracked_clients: int = 10_000,
    ) -> None:
        self._app = app
        self._capacity = capacity
        self._window_s = window_s
        self._path_prefix = path_prefix
        self._max_tracked_clients = max_tracked_clients
        self._buckets: dict[str, _TokenBucket] = {}
        self._buckets_lock = threading.Lock()

    def _bucket_for(self, key: str) -> _TokenBucket:
        with self._buckets_lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self._max_tracked_clients:
                    self._buckets.clear()  # crude bound; avoids unbounded per-IP growth
                bucket = _TokenBucket(self._capacity, self._window_s)
                self._buckets[key] = bucket
            return bucket

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if scope["type"] != "http" or not path.startswith(self._path_prefix):
            await self._app(scope, receive, send)
            return

        client = scope.get("client")
        key = client[0] if client else "unknown"
        if not self._bucket_for(key).allow():
            await _reject(
                send,
                429,
                "rate limit exceeded, try again shortly",
                extra_headers=[(b"retry-after", b"1")],
            )
            return

        await self._app(scope, receive, send)


class ConcurrencyLimiter:
    """Bounds concurrent in-flight calls to a single route (e.g. `/api/identify`).

    Handlers run synchronously in FastAPI's shared threadpool, so an unbounded burst of
    slow, memory-heavy photo requests can starve every other endpoint. This is a plain
    non-blocking semaphore, used as a context manager in the route handler; it returns
    `False` from `try_acquire()` rather than blocking, so an over-limit caller gets an
    immediate 503 instead of queuing behind a full threadpool.
    """

    def __init__(self, max_concurrency: int) -> None:
        self._semaphore = threading.Semaphore(max_concurrency)

    def try_acquire(self) -> bool:
        return self._semaphore.acquire(blocking=False)

    def release(self) -> None:
        self._semaphore.release()
