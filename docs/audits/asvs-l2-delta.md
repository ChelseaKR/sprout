# ASVS L2 delta — deployed HTTP surface

**Frame:** [ADR-0008](../adr/0008-asvs-l1-for-offline-mode.md) declares **ASVS 5.0 Level 1** for
Sprout's offline default (no auth surface, no required network ingress) and says the level "steps
up to L2" once an externally-exposed surface exists — the `serve` HTTP API behind a real URL
(RESEARCH-ROADMAP R4). This document is that step: it does not re-declare L1 or repeat the
supply-chain controls that already apply regardless of level (pip-audit, gitleaks, CodeQL, SHA-pinned
Actions — [`docs/RESPONSIBLE-TECH-AUDITS.md`](../RESPONSIBLE-TECH-AUDITS.md)); it covers **only the
delta a public, unauthenticated inference endpoint adds**, item by item, with the code or test that
satisfies it.

- **Author:** Chelsea Kelly-Reif
- **Scope:** `src/sprout/server.py`, `src/sprout/hardening.py` — the FastAPI app started by
  `sprout serve` / `create_app()`. Out of scope: the offline CLI/`sprout ask` path (never imports
  `sprout.server`, so nothing below touches it), and infrastructure not yet committed to this repo
  (TLS termination, CDN/WAF, budget alarm — deploy-target decisions that are sequenced with R4
  landing for real, not invented here).
- **Non-goal:** Sprout still has **no accounts and no per-user data** in this mode — V2
  (Authentication) and most of V4 (Access Control) genuinely have no surface to test, and are
  recorded as **N/A-with-reason** rather than silently omitted, per the framework's own discipline
  (`RESPONSIBLE-TECH-AUDITS.md`: "there is no silent default").

## Checklist

| ASVS 5.0 area | Requirement (paraphrased) | Status | Evidence |
|---|---|---|---|
| V1.1 Secure architecture | Documented threat model for the surface | Met | [`docs/THREAT-MODEL.md`](../THREAT-MODEL.md) STRIDE table already covers DoS/tampering/disclosure; this doc adds the control-level detail |
| V2 Authentication | Verifier requires authentication for sensitive operations | **N/A** — reference deployment is intentionally anonymous, read-only against a public corpus; no account, no session, no credential to attack | ADR-0008 |
| V4 Access control | Enforce authorization on every request | **N/A** — no per-user resource exists to authorize against in this mode (reminders are a local, unauthenticated demo store, not multi-tenant data) | `src/sprout/reminders.py` |
| V5.1 Input validation | Reject malformed/oversized input before it reaches business logic | Met | `_question_error()` bounds question length (`config.server.max_question_chars`); `image_b64` is base64-validated and rejected with 400 on failure (`server.py::identify`) |
| V5.2 Sanitization | No injected content reaches a shell/query/template unsanitized | Met (pre-existing) | Extractive generation + citation guard means model/user text never reaches a template unescaped; no SQL/shell surface exists |
| V11 (DoS-adjacent) Business logic / resource limits | Bound request size, request rate, and concurrency at the app layer, independent of any proxy | **Met (this PR)** | `RequestSizeLimitMiddleware` (`config.server.max_body_bytes`, default 12 MB — margin over an 8 MB photo at ~1.33x base64 inflation plus JSON overhead); `RateLimitMiddleware` (per-IP token bucket, `config.server.rate_limit_requests`/`rate_limit_window_s`, plus a stricter bucket on `/api/identify`); `ConcurrencyLimiter` bounds concurrent `/api/identify` calls (`config.server.identify_max_concurrency`) and returns 503 with `Retry-After` when saturated. Tests: `tests/test_hardening.py` |
| V13.2 API/service hardening | Send security headers appropriate to the API's content type | **Met (this PR)** | `SecurityHeadersMiddleware`: CSP (`default-src 'self'`, no inline script/style), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy` (camera/mic/geolocation/payment denied), `Cross-Origin-Opener-Policy`/`Cross-Origin-Resource-Policy: same-origin`, `Strict-Transport-Security` (inert until served over TLS, per deploy target). Applied to every response including ones rejected by the size/rate-limit layers. Tests: `tests/test_hardening.py::test_security_headers_present_on_every_response`, `::test_security_headers_present_on_rejected_responses` |
| V14.4 HTTP security headers | CSP present and restrictive | Met (this PR) | Same as above; `connect-src`/`img-src`/`font-src` scoped to `'self'` (+ `data:` for inline images), no `unsafe-inline` |
| V14.4 CORS | No wildcard CORS on a credentialed API | **N/A** — the app sets no `Access-Control-Allow-Origin` at all; it is same-origin by default (the bundled UI is served from the same origin) and issues no credentials to reflect | `server.py` mounts `web/dist` at `/` |
| V7 Error handling / logging | Errors do not leak internals; security-relevant events are logged | Met (pre-existing + extended) | `Logger` allow-lists fields (`obs.py::_ALLOWED_FIELDS`) so no PII/question text reaches logs; 4xx/5xx bodies from the new middleware carry a fixed, generic `{"error": ...}` string, never a stack trace |
| V1.2 Component access | Private engine internals not reached through a public seam | **Met (this PR)** | `Assistant.index_size()` replaces `readyz`/`health` reading `engine._store` directly (`answer.py`) |
| — Rate-limit statefulness | Rate limiting must not silently stop working under scale | Known limitation, documented | Buckets are process-local/in-memory — correct for the single-instance reference deployment this PR targets; a multi-instance deploy needs a shared store (e.g. Redis) before that limitation is retired. Tracked, not hidden |
| — Budget/cost controls | Runaway spend on the cloud generation seam is bounded | Met (pre-existing, out of scope for this PR) | `generation.max_cost_usd` (0.05/answer) fails closed on the provider seam; per-deploy-target cloud budget-alarm *infrastructure* (CDK) is explicitly deferred to when R4 lands for real (no `infra/` deploy target is committed yet) — see `docs/ideation/02-large-scale-fixes.md` FIX-10 |

## What "Met" means here

Every "Met (this PR)" row has a passing test in `tests/test_hardening.py` or
`tests/test_server.py`; this checklist is a mapping from ASVS language to that code, not a
separate claim. Re-run `make test` to reverify; a regression here fails the same coverage/test
gate as everything else in the repo, it is not a special-cased audit.

## What this explicitly does not cover

- **Reverse-proxy-level controls** (TLS termination, WAF, CDN-layer rate limiting, HSTS preload
  list submission) — these depend on the actual deploy target chosen when R4 ships and are
  intentionally not invented speculatively here; the app-level guards above are the ones that must
  hold *regardless* of what that proxy does or doesn't do.
- **Budget-alarm infrastructure** (AWS Budgets/CDK wiring) — same reasoning; the cost *ceiling* on
  the answer path is already enforced in code (`generation.max_cost_usd`), the *alarm* is
  infrastructure that belongs with the real deploy target, not this file-only PR.
- **Family Greenhouse personalization's L2 trigger** — a genuinely separate, larger review gate
  (per-user household data) that ADR-0008 already scopes as its own future decision.

## Revisit when

- The rate-limit buckets need to survive a process restart or span multiple instances.
- A reverse-proxy config is committed (`infra/`) — at that point, cross-check its CSP/rate-limit/
  body-size settings against this doc so the two layers agree rather than silently diverging.
- Family Greenhouse read-only personalization (Phase A, per `CLAUDE.md`) lands and introduces the
  first per-user data flow — that is the actual authentication/authorization trigger V2/V4 above
  are marked N/A against today.
