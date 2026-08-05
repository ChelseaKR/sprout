# 11. Local-first, offline reminder scheduler

- Status: Accepted
- Date: 2026-06-29
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (maintainer)
- Web-surface amendment: [ADR 0015](0015-web-is-a-reference-and-assurance-surface.md)

## Context

A care assistant that can answer "how often should I water this?" is naturally asked to
*remember* it. Watering and fertilizing reminders are the obvious next feature. But reminders
introduce two things Sprout has deliberately avoided so far: **persistent user state** and a
temptation to present a cadence as a fact. Both must be reconciled with the project's posture:
offline by default, no database, no user-query persistence in the demo, PII-free observability,
and "only the cited corpus is a source of fact."

## Decision

Reminders are **local-first and opt-in** (`reminders.py`, `config.py::RemindersConfig`):

1. **Storage is one JSON file on the user's own machine** (`var/reminders.json` by default).
   No database, no server-side state, nothing leaves the device. The file is created lazily —
   the first `remind add` / `POST /api/reminders` — so a user who never sets a reminder has no
   stored state, preserving the privacy-preserving default.
2. **The cadence is the user's setting, not a cited fact.** A reminder ties a plant (a corpus
   species slug or a free label) to an interval the *user* chooses (sensible per-task defaults
   are offered, never asserted). It may optionally record the citation/"as of" that motivated
   it, but the interval is never rendered as grounded horticultural guidance — the same
   corpus-vs-user-data boundary used for the photo-ID and Family-Greenhouse paths.
3. **Deterministic and clock-injectable.** The store takes an injectable clock; reminder ids
   are a content+position hash, so scheduling arithmetic and ids are reproducible and unit-
   testable offline (`test_reminders.py`). `complete()` reschedules `next_due = today +
   interval`.
4. **Observability stays PII-free.** Reminder *content* (plant labels, notes) is never logged;
   only event names and counts pass the existing whitelist logger, so the Tier-C posture holds.
5. **Available through local contracts.** A `sprout remind` CLI sub-app
   (add/list/due/done/remove) and JSON endpoints (`/api/reminders`, `/due`,
   `/{id}/complete`, `DELETE`) retain the offline reference capability. ADR 0015
   removes the reminder panel from the public web interface: household tasks and
   notifications belong in Family Greenhouse.

## Consequences

- **Positive.** The feature works fully offline with no account, no network, and no new
  dependency, so it "survives without funding" like the rest of the project. It is consistent
  with the no-database / config-over-code architecture: recovery is "the JSON file."
- **Positive.** Privacy is the default, not a mode: no reminder, no state; and reminder content
  never reaches the logs.
- **Negative — the honest limit.** Local-only storage means reminders do not sync across
  devices and there is no push/notification delivery in this phase. Proactive delivery
  (web push / email / SMS) is explicitly deferred to the Family-Greenhouse integration, which
  already owns notification channels (README, Phase B) — Sprout should not grow a second one.
  `sprout remind export --ics` (EXP-10, `docs/ideation/03-expansions.md`) makes that limit
  livable without adding a channel: it is a pure, one-directional function from
  `ReminderStore.all_reminders()` to an RFC 5545 `.ics` text (`src/sprout/ics.py`), so the
  user's own calendar app becomes the notifier. There is no import path — Sprout never reads
  an `.ics` file back — so the reminders JSON file remains the single source of truth and no
  new sync/push/account surface is introduced.
- **Negative.** A shared/multi-user deployment would need per-user isolation and auth around
  the store; the local-first design targets the single-user offline case and leaves
  multi-tenant concerns to a future ASVS-L2 phase, like household personalization.
- **Neutral.** The store path is config-driven, so an adopter can relocate or sandbox it.
