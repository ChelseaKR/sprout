# 8. ASVS L1 for offline mode

- Status: Accepted
- Date: 2026-06-22
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)

## Context

`SECURITY-AND-SUPPLY-CHAIN-STANDARD` requires every repo to declare an **OWASP ASVS 5.0**
level in `docs/RESPONSIBLE-TECH-AUDITS.md` — "there is no silent default; a repo with no
declaration fails review." The level is driven by the data the system touches and the
attack surface it exposes:

- **L1** is the default floor, "achievable with automated tooling alone," and maps to the
  AUTO-GATE set (parameterized queries, output encoding, TLS, server-side authz). The
  standard explicitly carves out that a repo with "no authentication, no authorization
  surface, and no network ingress" — a pure offline CLI or library — may declare its level
  accordingly, while still inheriting all of supply-chain scanning.
- **L2** is required for repos that touch **PII / identity / location**.

Sprout in its default, shipped configuration is an offline CLI plus a local
question-answer pipeline: no accounts, no auth, no user-data persistence (the demo server
persists no queries), no network ingress in the path that runs `make eval`/`sprout ask`.
The Family Greenhouse personalization path *would* introduce per-user household data
(locations, care history) — genuine PII — and therefore a higher bar.

## Decision

Sprout declares **ASVS 5.0 Level 1** for its offline default mode, enforced entirely by the
AUTO-GATE security set, and **defers ASVS L2** to the Family Greenhouse personalization
phase.

- **L1 posture.** No auth/authz surface and no required network ingress in the default
  path; secrets (Bedrock/Anthropic keys, regions) come from environment variables, never
  committed (`config.py`); no user-query persistence in the demo. Supply-chain controls are
  *not* waived: **pip-audit, gitleaks, Semgrep, CodeQL, SHA-pinned Actions, and SBOM on
  release** apply regardless (per the standard, scanning is never N/A for code that ships).
- **Defense-in-depth for the optional network seam.** When the cloud generator is enabled,
  `redact_pii()` scrubs email/SSN/phone patterns from text sent to a provider, and
  prompt-injection attempts are detected and logged (defense is structural via the citation
  guard — ADR-0003 — not the detector).
- **L2 is deferred, not skipped.** The README and ROADMAP record that the household-data
  path (field-level authz, cross-tenant isolation, the sentinel-PII data-flow proof) raises
  the target to **ASVS L2** when that phase lands; the declaration flips at that point
  rather than being assumed now.

## Consequences

- **Positive.** The declared level matches the actual blast radius: an offline tool with no
  identity surface is not held to authz integration tests it has no surface for, while still
  carrying the full supply-chain gate set.
- **Positive.** The deferral is explicit and dated, so adding personalization is a
  *gated* event (the first per-user data flow triggers the L2 review-gate), not a silent
  downgrade.
- **Negative.** A future contributor who adds a network ingress or a persistence layer to
  the default path would invalidate the L1 declaration; this ADR plus the
  `RESPONSIBLE-TECH-AUDITS` declaration are the tripwire that should force a re-evaluation.
- **Neutral.** The cloud seam's PII redaction and injection detection are L1-appropriate
  hygiene, not an L2 control; they do not change the declared level.
