# ADR 0013: Family Greenhouse is a first-party API integration

- Status: accepted
- Date: 2026-07-12

## Context

Family Greenhouse owns household plant records, tasks, authentication, and
confirmed task writes. Sprout owns the public horticultural corpus, grounded
answer pipeline, citations, and evaluation harness. The repositories also use
different licenses: Family Greenhouse is ELv2 and Sprout is Apache-2.0.

## Decision

Keep the products and repositories separate. Family Greenhouse calls Sprout
server-to-server through `POST /api/integrations/family-greenhouse/chat`.
Requests use a five-minute HMAC timestamp window and contain only coarse plant
species/light selectors plus relative task timing. Unknown fields are rejected,
which mechanically excludes names, notes, photos, people, addresses, exact
coordinates, and stable household identifiers.

Household data may select relevant corpus passages and may produce separately
labeled household observations. It is never accepted as horticultural evidence.
All care claims returned by Sprout remain corpus-derived and cited. Phase A is
read-only; any later task mutation remains a separate, explicit confirmation in
Family Greenhouse.

## Consequences

- Sprout remains independently useful and publicly reusable.
- Family Greenhouse can disable or roll back the integration with one feature
  flag and retains its current Bedrock assistant as a temporary fallback.
- The two deployments must rotate a shared HMAC secret and keep clocks within
  five minutes.
- Contract and privacy sentinel tests run in both repositories.
