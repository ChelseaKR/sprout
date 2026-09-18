# 23. Google Analytics 4 on the published site, guarded and disclosed

- Status: Accepted
- Date: 2026-09-17
- Author: Chelsea Kelly-Reif
- Deciders: Chelsea Kelly-Reif (owner decision, 2026-09-17)

## Context

Until now sprout.chelseakr.com ran no analytics. `web-static/README.md` said the reference had
"no telemetry", and the privacy audit's inventory had no row for people reading the site.

On 2026-09-17 the owner decided that every public site in the portfolio runs Google Analytics 4,
with privacy pages and claims changed so nothing published becomes false. The property was
provisioned the same day: GA4 property 554859638, web stream measurement ID `G-GS5D3FB3XL`, event
data retention 14 months, Google signals disabled on the property.

The published site is two builds in one tree: the MkDocs handbook, and the zero-server reference
(`web-static/public/`), which the Pages workflow copies over the handbook's root. Hard rule 4
(offline by default) governs the assistant, not page-view counting, and the reference's promise
that a question never leaves the tab is the one this change must not touch.

## Decision

**One shared loader, `web-static/public/analytics.js`, holds the ID and every guard.** The
reference page loads it from `<head>`. `docs_hooks/analytics.py` adds the same
`<script src="/analytics.js">` and the footer block to every handbook page at build time. Set
`MEASUREMENT_ID` to `""` and nothing loads from Google anywhere. The local server UI
(`web/dist/`), the CLI and the eval harness do not load it.

**When nothing loads.** The loader returns before creating `dataLayer` or requesting gtag.js:

- off `sprout.chelseakr.com`, so `mkdocs serve`, the test suite, CI and any other copy never
  contact Google;
- when `navigator.globalPrivacyControl === true`;
- when `navigator.doNotTrack`, `window.doNotTrack` or `navigator.msDoNotTrack` is `"1"` or `"yes"`;
- when `localStorage["sprout:analytics-opt-out"]` is `"1"`, which the footer's "Opt out of
  analytics" control writes. The control also sets Google's `window["ga-disable-G-GS5D3FB3XL"]`
  and toggles to "Opt back in". It is a `<button>` because it changes a setting, it stays
  `hidden` without JavaScript, and under GPC, DNT or blocked storage it shows no button and says
  why in its `role="status"` line. The shared stylesheet's generic `button { display:
  inline-flex }` would beat the `hidden` attribute, so `web/dist/styles.css` restates it.

**How it is configured.** Consent Mode v2 defaults deny `ad_storage`, `ad_user_data` and
`ad_personalization` everywhere, and deny `analytics_storage` through `region` for the 27 EU
states, Iceland, Liechtenstein, Norway, the UK and Switzerland, granting it elsewhere. There is no
consent banner, so nothing updates those defaults; readers in those regions get no GA cookie and
gtag sends Google cookieless pings, which the owner accepted. The config sets
`allow_google_signals: false` and `allow_ad_personalization_signals: false`, with `page_location`
cut to origin, path and `utm_*` parameters and `page_referrer` to the referring origin.

**Not a single-page app.** The handbook is ordinary MkDocs pages (Material's instant navigation is
off) and the reference is one page that never changes its address, so gtag's page view on
`config` is the page view.

**The question never reaches GA.** The reference keeps the question in the tab; it is never in a
page address, a title or anything the loader reads. `/privacy/` says so.

**The offline shell is unchanged.** `analytics.js` is not in the service worker's `SHELL`: it is
not needed for the page to answer, and caching it would only run the loader offline, where it can
do nothing. `sprout offline-check` requires only what the page needs to run.

**No CSP change.** GitHub Pages sends no Content-Security-Policy, and no page carries a CSP meta
tag. A future CSP would need `https://www.googletagmanager.com` in `script-src` and
`https://*.google-analytics.com https://*.analytics.google.com` in `connect-src` and `img-src`.

## Consequences

- Reading the site now sends Google a page view with the cut-down address, the referring origin,
  browser and device data and an approximate location, and outside the EEA, UK and Switzerland
  sets the `_ga` cookies for up to two years. `/privacy/` (English and Spanish, in the handbook
  nav and the sitemap), README, `web-static/README.md` and `docs/RESPONSIBLE-TECH-AUDITS.md` §C say
  so.
- `tests/test_analytics.py` runs the loader in Node against stubbed browser objects, checks the
  hook against a real handbook page, and holds the reference page's footer equal to the hook's.
  Removing the hostname, GPC, DNT or opt-out guard is caught by a negative control that first
  asserts its sabotage landed.
- **Owner steps in the GA4 web stream:** "Form interactions" would record the reference's
  question form by id and never its text; turn it off unless it is wanted. "Site search" has no
  query parameter to read here.
