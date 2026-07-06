# Accessibility Statement — Sprout

**Last updated:** 2026-06-22 · **Version:** 0.1.0 · **Maintainer:** Chelsea Kelly-Reif

Sprout is committed to being usable by everyone, including people who use assistive technology.
Accessibility is a merge-blocking requirement here, not an aspiration: a regression fails the
build.

## Conformance status

Sprout targets and substantially conforms to **WCAG 2.2 Level AA** across its three HTML surfaces —
the chat UI, the HTML evaluation report, and the static non-chat transcript view. Because the
Revised Section 508 Standards (36 CFR Part 1194) incorporate WCAG 2.0 A/AA by reference, and 2.2 AA
is a superset, Sprout also conforms to the 508 web-content obligation. A full
**Accessibility Conformance Report (VPAT 2.5, Rev 508)** is published at
[`docs/accessibility/ACR.md`](../accessibility/ACR.md).

"Substantially conforms" is honest: see **Known gaps** below.

Sprout is a houseplant-care reference implementation, not federal ICT, so Section 508 is not legally
required. We build and publish to it anyway — to demonstrate the assistant against the standard
buyers actually audit to.

## How this is verified

**Corrected 2026-07-05** — a conformance audit found this section overstated what actually gates.
The honest breakdown:

- **Automated, merge-blocking today:** a deterministic structural self-check
  (`sprout a11y-check`) that runs on both the chat UI and the generated eval report and **fails
  closed** — Sprout will not emit an inaccessible report. This is genuinely wired into `make verify`
  and the required `ci-gate` check.
- **Automated, advisory only (not yet merge-blocking):** axe-core and pa11y-ci both run inside the
  `pa11y` CI job, which is `continue-on-error: true` and excluded from `ci-gate` — a violation is
  visible in CI logs but does not fail a PR. Wiring this to blocking is tracked (gap tracked;
  planned in `docs/ROADMAP.md`).
- **Not yet wired:** Lighthouse CI accessibility scoring does not exist in this repo yet, despite
  being referenced below in the past. Tracked as a gap, not silently dropped.
- **Manual, per release — not yet performed:** a keyboard-only walkthrough and screen-reader review
  (NVDA + Firefox, VoiceOver + Safari) is planned per release but has not yet been carried out; no
  dated walkthrough artifact exists yet. A prior version of this statement cited
  `docs/a11y/screen-reader-walkthrough-2026-06-22.md`, which was never created — that reference is
  removed here and will be restored, with a real dated file, once the walkthrough is actually done.

`make verify` runs the structural self-check above; it does not yet run pa11y/axe/Lighthouse
(those are CI-only, and advisory as described above).

## What we have done

- Skip link, semantic landmarks, and a logical heading order on every surface.
- Labeled controls; the language choice is a real `<fieldset>`/`<legend>` radio group.
- A visible, high-contrast focus ring; pointer targets at least 44×44 px.
- Color is never the only signal: the toxicity warning is labeled "Safety," every sentence carries
  a bracketed `[citation]` marker, and low confidence is announced in words.
- Streamed answers and status are announced through polite live regions without stealing focus; the
  toxicity warning uses an assertive alert.
- A **static, paginated transcript alternate** renders the same questions, answers, and citations
  for users who cannot operate a live chat.
- Reduced motion is honored via `prefers-reduced-motion`.
- English and Spanish each render the correct page language attribute.

## Known gaps

We would rather state these than hide them:

1. **Wide tables at very small widths.** On the eval report and transcript, an unusually long
   failing-example "Detail" cell can cause horizontal scrolling of that table at 320 px wide. No
   content is lost. A responsive-table fix is tracked. (WCAG 1.4.10)
2. **Single-page navigation.** The eval report and transcript are single linear documents reached
   one way; navigation within them relies on landmarks and headings rather than multiple navigation
   paths. (WCAG 2.4.5, documented exception for single-page artifacts)
3. **Readability of grounded answer prose.** Answer text is extracted verbatim from the
   horticulture corpus and is not readability-graded, so an individual answer may read above a
   target grade level. UI copy, labels, and errors are written in plain language. (Functional
   Performance Criterion 302.9 — review-gated, not auto-gated)

None of these block keyboard or screen-reader operation of any primary task.

## Feedback and contact

If you hit an accessibility barrier in Sprout — or you have a fix — please tell us. We aim to
respond within five business days.

- **Email:** ckellyreif@gmail.com
- **Issues:** open an issue on the project repository (please include the surface, your browser, and
  any assistive technology in use)

When you report a barrier, we will confirm receipt, describe a remedy or workaround, and track the
fix to a release.

## Scope and limits

- This statement covers Sprout's offline/default configuration (the bundled, synthetic CC0 corpus).
- The optional cloud generator and the deferred Family Greenhouse personalization surfaces are out
  of scope for this statement and will be re-assessed when shipped.
- Sprout is not veterinary or medical advice.

*This statement is reviewed and re-dated on each release, alongside the ACR and the screen-reader
walkthrough.*
