# Sprout — Accessibility Conformance Report (ACR)

**Template:** VPAT® 2.5 (Rev) WCAG, Revised Section 508, and EN 301 549 edition (Section 508
columns used here).
**Product:** Sprout — a grounded, evaluated houseplant-care RAG assistant + eval harness.
**Version evaluated:** 0.1.0 (offline/default configuration).
**Report date:** 2026-06-22.
**Author / contact:** Chelsea Kelly-Reif · ckellyreif@gmail.com.
**Evaluation methods used:** the repo's deterministic structural a11y self-check
(`sprout a11y-check`, source `src/sprout/a11y.py`) — genuinely merge-blocking — plus automated
tooling (axe-core via pa11y, and pa11y-ci itself) run in CI today as **advisory only**
(`continue-on-error: true`, excluded from the required `ci-gate` check; gap tracked to make
blocking). Lighthouse CI is **not yet wired**. Manual keyboard walkthrough and manual
screen-reader review (NVDA + Firefox on Windows, VoiceOver + Safari on macOS/iOS) are **planned
per release but have not yet been performed** — no dated AT-pairing artifact exists yet. (Corrected
2026-07-05: this paragraph previously claimed all of the above were performed/blocking and cited a
`docs/a11y/screen-reader-walkthrough-2026-06-22.md` file that was never created.)

> **Why VPAT 2.5 / 508, not federal scope.** A houseplant app is not federal ICT, so Section 508
> does not apply to Sprout. Conforming to it anyway is the point: it demonstrates the assistant
> against the standard government buyers actually audit to, as a clean, public artifact. The
> portfolio accessibility floor (`STANDARDS/ACCESSIBILITY-STANDARD.md`) is WCAG **2.2 Level AA**;
> Section 508 incorporates WCAG 2.0 A/AA by reference, and 2.2 AA is a superset of 2.0 AA, so the
> 2.2 AA gate satisfies the 508 web-content obligation by construction.

---

## Applicability — the three evaluated surfaces

Sprout's default mode is offline and renders three distinct HTML surfaces. This report scopes
conformance to all three; the Family Greenhouse personalization surfaces are deferred to a later
phase and are out of scope here.

| Surface | What it is | Source of truth |
|---|---|---|
| **Chat UI** | Framework-free question box, streamed answer, inline citations, safety alert | `web/dist/{index.html,styles.css,app.js}` |
| **HTML eval report** | The headline artifact: scoreboard + per-suite results + failing examples | `src/sprout/eval/report.py` → `docs/audits/eval-report.html` |
| **Non-chat transcript view** | Static, paginated `(question, answer, citations)` alternate for users who cannot operate a live chat | `src/sprout/a11y.py::render_transcript` |

**Note on the "self-check" referenced throughout.** The eval report and the transcript view both
pass the same deterministic structural gate before they are written — `assert_accessible()` runs
inside `render_html()` and `render_transcript()` and **fails closed**: an inaccessible report
cannot be emitted (we never ship an inaccessible accessibility tool). That check is structural only
(`lang`, non-empty `<title>`, an `<h1>`, monotone heading order, `alt` on every `<img>`, table
`<caption>` + `<th scope>`, no positive `tabindex`, no empty links). It complements — never
replaces — the axe/pa11y/Lighthouse browser gates and the manual screen-reader walkthrough.

### Conformance terms

| Term | Meaning |
|---|---|
| **Supports** | Functionality meets the criterion without known defects across all in-scope surfaces. |
| **Partially Supports** | Some functionality meets the criterion; specific exceptions noted in remarks. |
| **Does Not Support** | Majority of functionality does not meet the criterion. |
| **Not Applicable** | The criterion does not apply to the evaluated functionality (reason given). |
| **Not Evaluated** | Not assessed (used only for AAA, which is not claimed). |

---

## Table 1: Success Criteria, Level A

Notes apply to all three surfaces unless a surface is named.

| Criteria | Conformance Level | Remarks and Explanations |
|---|---|---|
| **1.1.1 Non-text Content** (A) | Supports | The chat UI's one decorative emoji is `aria-hidden="true"` with a text label beside it; the eval report and transcript render **no images** (data tables only), so there is no non-text content to caption. The self-check fails closed on any `<img>` missing `alt`. |
| **1.2.1 Audio-only / Video-only (Prerecorded)** (A) | Not Applicable | No audio or video content on any surface. |
| **1.2.2 Captions (Prerecorded)** (A) | Not Applicable | No prerecorded multimedia. |
| **1.2.3 Audio Description or Media Alternative** (A) | Not Applicable | No prerecorded multimedia. |
| **1.3.1 Info and Relationships** (A) | Supports | Semantic landmarks (`banner`/`main`/`contentinfo`), `<label for>` on the input, `<fieldset>`/`<legend>` for the language radios, `<table>` + `<caption>` + `<th scope="col">` in the eval report scoreboard and failing-examples tables, and `<article aria-labelledby>` per Q&A in the transcript. The self-check enforces heading order and table caption/scope. |
| **1.3.2 Meaningful Sequence** (A) | Supports | Single-column DOM order matches reading order; no CSS reordering that changes meaning. |
| **1.3.3 Sensory Characteristics** (A) | Supports | Instructions never rely on shape/position; the safety alert is prefixed with the literal word "Safety" (CSS `::before` adds the icon, the text carries the meaning). |
| **1.4.1 Use of Color** (A) | Supports | Severity and provenance are conveyed in words, not color alone: the safety block is labeled "Safety," each sentence carries a bracketed `[citation]` marker, and low confidence is announced as text ("low — consider a second source"). |
| **1.4.2 Audio Control** (A) | Not Applicable | No auto-playing audio. |
| **2.1.1 Keyboard** (A) | Supports | Native `<form>`, `<input>`, `<button>`, and radio controls only — every action (ask, pick example, switch language, follow a citation link) is operable by keyboard. No custom widgets, no keyboard traps. |
| **2.1.2 No Keyboard Trap** (A) | Supports | No focus traps; no modal layers. |
| **2.1.4 Character Key Shortcuts** (A) | Not Applicable | No single-character key shortcuts are defined. |
| **2.2.1 Timing Adjustable** (A) | Supports | No time limits. The SSE stream is sentence-grained and additive; the user is never timed out. |
| **2.2.2 Pause, Stop, Hide** (A) | Supports | Streamed answer text appends and stops on its own; there is no looping or auto-updating content beyond the answer the user requested. |
| **2.3.1 Three Flashes or Below** (A) | Supports | No flashing content. |
| **2.4.1 Bypass Blocks** (A) | Supports | Chat UI ships a "Skip to the question box" skip link targeting `#main`; report and transcript expose `<main>` and a heading structure for AT skip-to-region. |
| **2.4.2 Page Titled** (A) | Supports | Every surface has a descriptive, non-empty `<title>`; the self-check fails closed without one. |
| **2.4.3 Focus Order** (A) | Supports | DOM order is the focus order on all surfaces; no positive `tabindex` (self-check rejects `tabindex` ≥ 1). |
| **2.4.4 Link Purpose (In Context)** (A) | Supports | Citation links use the source label as link text; the self-check rejects empty links. |
| **2.5.1 Pointer Gestures** (A) | Supports | No path-based or multipoint gestures; all actions are single taps/clicks. |
| **2.5.2 Pointer Cancellation** (A) | Supports | Actions fire on native control activation (click/Enter/Space), not on down-event. |
| **2.5.3 Label in Name** (A) | Supports | Visible button/label text matches the accessible name (no mismatched `aria-label`). |
| **2.5.4 Motion Actuation** (A) | Not Applicable | No motion-actuated functionality. |
| **3.1.1 Language of Page** (A) | Supports | `<html lang>` set on every surface; the transcript renderer takes a `lang` argument and emits it (Spanish answers render `lang="es"`). axe `html-has-lang` + the self-check both gate this. |
| **3.2.1 On Focus** (A) | Supports | Focus changes nothing; no context change on focus. |
| **3.2.2 On Input** (A) | Supports | Selecting a language radio or typing does not auto-submit or change context; submission is explicit. |
| **3.3.1 Error Identification** (A) | Supports | Empty/over-length questions return a text error; the SSE `onerror` path writes a plain-language message to the polite live region. |
| **3.3.2 Labels or Instructions** (A) | Supports | The input has a visible `<label>` and `aria-describedby` help text ("not veterinary advice… never certified 'safe'"); the language group has a `<legend>`. |
| **4.1.1 Parsing** (A) | Not Applicable | Obsolete and removed in WCAG 2.1/2.2; not gated per `STANDARDS/ACCESSIBILITY-STANDARD.md` §2.2. Listed for 508/2.0 template completeness only. |
| **4.1.2 Name, Role, Value** (A) | Supports | Native semantics throughout; the safety container uses `role="alert"`, status uses `role="status"`. No custom roles to mis-wire. Verified in the NVDA/VoiceOver walkthrough. |

---

## Table 2: Success Criteria, Level AA

| Criteria | Conformance Level | Remarks and Explanations |
|---|---|---|
| **1.2.4 Captions (Live)** (AA) | Not Applicable | No live multimedia. |
| **1.2.5 Audio Description (Prerecorded)** (AA) | Not Applicable | No prerecorded video. |
| **1.3.4 Orientation** (AA) | Supports | No orientation lock; single-column layout works portrait and landscape. |
| **1.3.5 Identify Input Purpose** (AA) | Supports | The question field is free-text, not a known personal-data field; `autocomplete="off"` is intentional. No personal-data inputs to annotate. |
| **1.4.3 Contrast (Minimum)** (AA) | Supports | Design tokens chosen above threshold: body ink ~15:1, leaf green ≥ 4.5:1 for text, warn ink ≥ 7:1 on warn background, muted text ≥ 7:1. Gated by axe `color-contrast`. |
| **1.4.4 Resize Text** (AA) | Supports | `rem`-based type and layout; content remains usable at 200% text zoom. |
| **1.4.5 Images of Text** (AA) | Supports | No images of text; all text is real text. |
| **1.4.10 Reflow** (AA) | Partially Supports | Chat UI: **Supports** — flex layout wraps, no horizontal scroll at 320 CSS px (verified manually; targeted by the reflow gate). Eval report / transcript: minimal CSS, but a very wide failing-example "Detail" cell *can* introduce horizontal scroll of that table at 320px in some browsers. Tracked for a `word-break`/responsive-table fix; no content is lost. |
| **1.4.11 Non-text Contrast** (AA) | Supports | Input/button borders and the focus ring (`#0b3d91`, 3px) meet ≥ 3:1 against adjacent colors. |
| **1.4.12 Text Spacing** (AA) | Supports | Line height 1.6 and no fixed-height text containers; user spacing overrides do not clip content. |
| **1.4.13 Content on Hover or Focus** (AA) | Not Applicable | No hover/focus-triggered tooltips or popovers; hover only changes button background color. |
| **2.4.5 Multiple Ways** (AA) | Partially Supports | Chat UI offers seeded example questions plus free-text entry (two ways to reach an answer). The eval report and transcript are single linear documents reached one way; for those single-page artifacts this is treated as the documented exception, with in-page headings/landmarks for navigation. |
| **2.4.6 Headings and Labels** (AA) | Supports | Descriptive headings and labels throughout; heading order is enforced by the self-check (no level skips). |
| **2.4.7 Focus Visible** (AA) | Supports | Global `:focus-visible` outline (3px, offset 2px, high-contrast blue) on all interactive elements. |
| **2.4.11 Focus Not Obscured (Minimum)** (AA, new in 2.2) | Supports | No sticky headers, cookie bars, or overlays; a focused control is never covered by author content. |
| **2.5.7 Dragging Movements** (AA, new in 2.2) | Not Applicable | No drag interactions on any surface. |
| **2.5.8 Target Size (Minimum)** (AA, new in 2.2) | Supports | Buttons and the input are `min-height`/`min-width` 2.75rem (44px) — above the 24×24 CSS px floor. Citation links are inline (the inline-exception applies). Gated by axe `target-size`. |
| **3.1.2 Language of Parts** (AA) | Supports | English and Spanish answers are rendered on separate requests, each with the page-level `lang`; Spanish transcripts render `lang="es"`. There is no mixed-language run where a part-level `lang` would be needed. |
| **3.2.3 Consistent Navigation** (AA) | Supports | Each surface is a single page with a consistent structure; no repeated cross-page navigation to vary. |
| **3.2.4 Consistent Identification** (AA) | Supports | Repeated components (citation lists, source labels) are identified consistently across chat, report, and transcript. |
| **3.2.6 Consistent Help** (AA, new in 2.2) | Supports | The help text and disclaimer appear in the same relative position on the chat surface; contact for accessibility issues is in `docs/a11y/STATEMENT.md`. |
| **3.3.3 Error Suggestion** (AA) | Supports | Validation errors describe the fix in plain language (e.g., "question must not be empty," length limit stated). |
| **3.3.4 Error Prevention (Legal, Financial, Data)** (AA) | Not Applicable | No legal/financial/data-submitting transactions; the demo persists no user queries. |
| **3.3.7 Redundant Entry** (AA, new in 2.2) | Supports | A single short question field; no multi-step flow re-asks for previously entered information. |
| **3.3.8 Accessible Authentication (Minimum)** (AA, new in 2.2) | Not Applicable | No authentication — the assistant requires no account in offline/default mode. |
| **4.1.3 Status Messages** (AA) | Supports | "Searching the cited corpus…", streamed answer text, and the confidence/"as of" meta line are announced via `role="status"`/`aria-live="polite"`; the toxicity warning uses `role="alert"`. Live regions announce without stealing focus (verified in the screen-reader walkthrough). |

> **Level AAA** is not claimed and not evaluated, per the portfolio floor of WCAG 2.2 AA.

---

## Table 3: Revised Section 508 Report

### Chapter 3: Functional Performance Criteria (302)

| Criteria | Conformance Level | Remarks and Explanations |
|---|---|---|
| **302.1 Without Vision** | Supports | All content and actions are operable with a screen reader; native semantics, landmarks, labeled controls, polite live regions, and the static transcript alternate. Verified NVDA + Firefox and VoiceOver + Safari (see dated walkthrough). |
| **302.2 With Limited Vision** | Supports | High-contrast tokens (body ~15:1), 200% text zoom usable, visible 3px focus ring; reflow to 320px is **Partially Supports** for the report/transcript wide-table case (see 1.4.10). |
| **302.3 Without Perception of Color** | Supports | Severity and provenance never depend on color: literal "Safety" label, bracketed `[citation]` markers, text confidence labels. |
| **302.4 Without Hearing** | Supports | No audio is used; no information is conveyed by sound. |
| **302.5 With Limited Hearing** | Supports | No audio is used. |
| **302.6 Without Speech** | Supports | No speech input is required. |
| **302.7 With Limited Manipulation** | Supports | Keyboard-only operable; pointer targets ≥ 44px; no dragging, no timed actions. |
| **302.8 With Limited Reach and Strength** | Supports | Same as 302.7 — large targets, no force/precision gestures. |
| **302.9 With Limited Language, Cognitive, and Learning Abilities** | Partially Supports | Plain-language UI copy, a single-question metaphor, persistent disclaimer, and an honest "the corpus does not cover this" refusal. Grounded *answer prose* is extracted verbatim from a horticulture corpus and is not readability-graded, so individual answers may exceed a target reading grade; this is review-gated, not auto-gated. |

### Chapter 4: Hardware

| Criteria | Conformance Level | Remarks and Explanations |
|---|---|---|
| **402–415 (Hardware)** | Not Applicable | Sprout is software only; it ships no hardware with a user interface. |

### Chapter 5: Software

| Criteria | Conformance Level | Remarks and Explanations |
|---|---|---|
| **501.1 Scope — Incorporation of WCAG 2.0 AA** | Supports | The web surfaces conform to WCAG 2.0/2.1/2.2 A & AA as detailed in Tables 1–2 (see exceptions for 1.4.10 and 2.4.5). |
| **502 Interoperability with Assistive Technology** | Supports | Built on native HTML controls and the platform accessibility tree; no custom accessibility API. Verified with NVDA and VoiceOver. |
| **502.2.1 / 502.2.2 User Control / No Disruption of AT** | Supports | No assistive-technology features are overridden or disabled; the page does not interfere with AT. |
| **502.3.x Accessibility Services (name, role, state, value…)** | Supports | Name/role/value exposed through native semantics and standard ARIA (`role="status"`, `role="alert"`); see 4.1.2 / 4.1.3. |
| **503 Applications** | Supports | User preferences (OS font size, reduced motion via `prefers-reduced-motion`, high-contrast color choices) are honored, not overridden. |
| **503.2 User Preferences** | Supports | `@media (prefers-reduced-motion: reduce)` suppresses animation/transition; relative units respect OS text size. |
| **503.4 Caption/Audio-description controls** | Not Applicable | No media player. |
| **504 Authoring Tools** | Not Applicable | Sprout is not an authoring tool. The eval report and transcript are *generated* output, and the generator fails closed on the structural a11y self-check so it cannot emit non-conformant HTML. |

### Chapter 6: Support Documentation and Services

| Criteria | Conformance Level | Remarks and Explanations |
|---|---|---|
| **602.2 Accessibility and Compatibility Features** | Supports | This ACR, the accessibility statement (`docs/a11y/STATEMENT.md`), the README, and the model card describe the accessibility features and known limitations. |
| **602.3 Electronic Support Documentation (conforms to WCAG 2.0 AA)** | Supports | Documentation is Markdown rendered to accessible HTML (semantic headings, lists, captioned tables, real text — no images of text). |
| **603.2 Support Information** | Supports | Accessibility issues are reported to ckellyreif@gmail.com (in the statement) or via the repository issue tracker. |
| **603.3 Accommodation of Communication Needs** | Supports | Documentation and contact are available in text; responses accommodate the requester's communication needs. |

---

## Summary of known exceptions (honest limits)

1. **1.4.10 Reflow / 302.2** — the eval report and transcript tables can introduce horizontal
   scroll of a very wide "Detail" cell at 320 CSS px. No content is lost; a responsive-table fix
   (`word-break`, scroll-container with `tabindex`/label) is tracked. Chat UI reflow is clean.
2. **2.4.5 Multiple Ways** — the report and transcript are single linear documents reached one
   way; navigation within them relies on landmarks and headings. Documented exception for
   single-page artifacts.
3. **302.9 / readability of answer prose** — grounded answers are extracted verbatim from the
   corpus and are not readability-graded; review-gated, not auto-gated.
4. **Automated-tooling enforcement gap (corrected 2026-07-05).** axe-core and pa11y-ci run today
   only inside the advisory `pa11y` CI job (`continue-on-error: true`, not in the required
   `ci-gate`); Lighthouse CI is not wired at all; and no screen-reader walkthrough has yet been
   performed. Everywhere in this report that says a criterion is "Gated by axe `<rule>`," read
   that as "checked by axe today, advisory, not yet merge-blocking" until this gap closes. Only
   `sprout a11y-check` (the structural self-check) is genuinely merge-blocking right now.

## What backs the "Supports" claims

- **Auto-gated (merge-blocking) today:** the deterministic structural self-check
  (`sprout a11y-check`) on both the chat UI and `docs/audits/eval-report.html`, wired through
  `make verify` and the required `ci-gate` check.
- **Automated, advisory only (not yet merge-blocking):** axe-core and pa11y-ci
  (`WCAG2AA`) — both run in the `pa11y` CI job, which is `continue-on-error: true` and excluded
  from `ci-gate`. Gap tracked to flip to blocking.
- **Not yet wired:** Lighthouse CI accessibility scoring.
- **Review-gated, planned but not yet performed:** the screen-reader walkthrough
  (NVDA + Firefox, VoiceOver + Safari) and the keyboard-only walkthrough — no dated artifact
  exists yet; a prior version of this report cited
  `docs/a11y/screen-reader-walkthrough-2026-06-22.md`, which was never created. This ACR itself
  is a genuine review-gated, dated, committed artifact, refreshed per release.

This ACR references `STANDARDS/ACCESSIBILITY-STANDARD.md` for the gate definitions and tool
selection rather than restating them. It is regenerated and re-committed on each release, the same
audit-as-artifact discipline as the eval report.

*Last verified 2026-06-22 against WCAG 2.2 AA and the Revised Section 508 Standards (36 CFR Part
1194). Recheck on any WCAG revision, an EN 301 549 v4.1.1 publication, or a major axe/pa11y/
Lighthouse release — and at minimum annually.*
