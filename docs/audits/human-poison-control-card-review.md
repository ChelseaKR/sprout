# Human poison-control escalation card — clinician review (PENDING)

**Status: NOT YET REVIEWED. This is a placeholder, not a sign-off.** The human-exposure
escalation card described below is implemented and wired end to end in code
(`GuardsConfig.child_exposure_keywords` / `animal_exposure_keywords`,
`guards.detect_exposure_type`, `PromptConfig.human_escalation_card_by_lang`) but is gated
behind `PromptConfig.human_card_reviewed`, which defaults to `False`. **No user sees this
card until that flag is flipped to `True`, and it must not be flipped until the section
below is filled in by a real reviewer.**

## Why this file exists

[`docs/ideation/02-large-scale-fixes.md` FIX-13](../ideation/02-large-scale-fixes.md) is
explicit: *"hard gate: no copy ships without review by a poison-control clinician /
medical toxicologist, in both languages — the numbers, the phrasing, and the decision to
include them at all are theirs to approve."* That gate is not a formality this file
satisfies by existing; it is satisfied only by a real reviewer completing the section
below, the same discipline
[`docs/RESEARCH-ROADMAP.md`](../RESEARCH-ROADMAP.md) already applies to the animal-line
escalation card (E9) and to the toxicity corpus generally ("Deferred: R1 toxicity corpus
+ R2 eval cases (need a veterinary-toxicologist / SME)").

## What a reviewer needs to approve

The candidate copy lives in `PromptConfig.human_escalation_card_by_lang` in
`src/sprout/config.py`. It currently reads (EN):

> If a child may have eaten part of this plant: Poison Control, 1-800-222-1222
> (https://www.poison.org/), free and available 24/7, or use webPOISONCONTROL
> (https://triage.webpoisoncontrol.org/) for online guidance. What to tell them: the
> plant (species if known), how much was eaten, and when.

and the parallel ES string in the same field. A qualified reviewer needs to confirm, for
**both languages**:

1. The number and URLs are current and correct for a general US audience.
2. The phrasing does not over- or under-state urgency relative to how a real
   poison-control intake call is triaged.
3. Showing this card *at all* — as opposed to, say, always directing to 911/emergency
   services for a child, or some other framing — is the right decision. This is called
   out explicitly in the ideation item as the reviewer's call, not this codebase's.
4. Any wording changes needed, in-line, in both languages.

## Sign-off record (fill in when complete)

| Field | Value |
|---|---|
| Reviewer name | _(pending)_ |
| Credential (e.g. board-certified medical toxicologist, poison-control clinician) | _(pending)_ |
| Date reviewed | _(pending)_ |
| Scope | EN copy / ES copy / both |
| Outcome | _(pending)_ |
| Changes requested | _(pending)_ |

Once this table is filled in with a real name, credential, and date, set
`PromptConfig.human_card_reviewed = True` in `src/sprout/config.py` in the same commit as
this file's update, and un-skip the eval cases marked `pending_clinician_review` in
`eval/suites/safety.yaml`.

## Scope note (non-US numbers)

Per the ideation item, non-US poison-control numbers are out of scope until Sprout has a
locale story beyond EN/ES-in-the-US — the same limit the existing animal-line card
(ASPCA APCC, Pet Poison Helpline) already carries.
