# ADR 0014: The public web interface is a reference and assurance surface

- Status: accepted
- Date: 2026-07-16

## Context

Sprout's headline artifact is its evaluation harness. Family Greenhouse owns the
household product: plant records, care history, tasks, authentication,
notifications, and confirmed writes (ADR 0013). A standalone Sprout interface
that also manages photos and reminders creates two overlapping plant-care apps,
weakens that ownership boundary, and gives a local-only workflow a misleading
consumer-product shape.

Sprout still needs a browser surface. Reviewers need to see citation, abstention,
safety, multilingual, streaming, and accessibility behavior without first
installing a CLI. Integrators and auditors also need a direct route from a live
answer to the evaluation evidence and architecture that justify it.

## Decision

The public Sprout web interface is a **stateless, corpus-only reference surface**.
Its primary interaction is one plant-care question followed by the rendered
answer or refusal, citations, freshness, confidence, and safety routing. The page
also exposes the source-to-answer claim chain, the current evaluation artifact,
documentation, and the product boundary with Family Greenhouse.

The public interface does not collect or manage household state. It has no plant
inventory, photo-upload workflow, care schedule, reminders, notifications,
authentication, personalization, or task-completion actions. Those user journeys
belong in Family Greenhouse, which calls Sprout through the first-party integration
contract.

The existing photo-identification and local-reminder CLI/JSON contracts remain
available for offline reference use and backward compatibility. They are not
promoted as destinations in the public web interface. Removing or versioning those
contracts is a separate API lifecycle decision.

## Consequences

- Sprout's web surface demonstrates its distinctive value instead of becoming a
  second household plant application.
- The live reference remains a merge-gated WCAG 2.2 AA surface for streaming,
  citation, refusal, language, and safety behavior.
- Family Greenhouse has one clear place for household state and action.
- The public page can be deployed without an account system or user-state model.
- CLI/API capabilities are temporarily broader than the public interface; their
  compatibility posture must remain explicit in documentation.
