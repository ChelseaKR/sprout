# Scoped OWASP ASVS Level 2 review — Family Greenhouse integration

**Reviewed:** 2026-07-12  
**Scope:** `POST /api/integrations/family-greenhouse/chat` and its Family Greenhouse caller  
**Target:** OWASP ASVS 5.0 Level 2 controls applicable to this narrow, stateless API boundary

## Result

No open high- or critical-severity findings. The boundary is approved for a
feature-flagged, read-only rollout. This is a scoped engineering review, not an
OWASP certification of every optional Sprout deployment.

| Control area | Implemented evidence |
|---|---|
| Authentication | HMAC-SHA256 over timestamp and canonical body; constant-time comparison |
| Replay resistance | Requests outside a five-minute clock window are rejected |
| Input validation | Strict typed schema, unknown-field rejection, bounded arrays/strings/ranges |
| Resource limits | 64 KiB body cap, at most 100 plants and 100 tasks |
| Privacy | No stable household/member IDs, names, notes, photos, locations, coordinates, or exact task timestamps in context; caller redacts known plant nicknames and common contact identifiers from the question |
| Authorization | Integration is read-only; Sprout exposes no Family Greenhouse mutation capability |
| Output integrity | Care prose remains extractive, citation-checked, corpus-provenance output |
| Error handling | Invalid auth is generic; secrets and raw questions are never logged |
| Transport | Production deployment requires HTTPS; the shared secret is resolved from Secrets Manager |
| Verification | Cross-repository unit tests cover authentication, replay window, PII sentinels, provenance, fallback, persistence, and citation replay |

## Residual risks

- Arbitrary free text can contain personal information not recognizable as a
  plant nickname, email address, or phone number. The integration is first-party,
  the question is never logged, and the UI should continue warning users not to
  include sensitive personal information.
- HMAC clock checking depends on synchronized service clocks. AWS-managed
  runtimes satisfy this operational assumption.
- Availability fallback temporarily returns to the existing Family Greenhouse
  Bedrock assistant; a structured event records that transition.

Re-review before adding proactive notifications, task write-back, a new context
field, a new caller, or a non-AWS deployment topology.
