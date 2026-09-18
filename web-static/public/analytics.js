// Google Analytics 4 on the published site, and the footer's opt-out
// (docs/adr/0023-google-analytics-4-on-the-published-site.md).
//
// The owner decided on 2026-09-17 to run GA4 on every public site in the portfolio,
// with the privacy copy changed to match. This file is the one place that decision
// is implemented, and MEASUREMENT_ID below is the one place the property's
// measurement ID lives. It is public (every page that loads GA hands it to the
// browser), so it is committed as site configuration. Set it to "" and nothing
// loads from Google on any page.
//
// Loaded from <head> by the reference page (web-static/public/index.html) and, via
// docs_hooks/analytics.py, by every MkDocs page. It does two things:
//
// 1. Wires the footer's "Opt out of analytics" control on every host, so it can be
//    exercised anywhere. "Opt out" stores the choice in localStorage and sets
//    Google's own window["ga-disable-<ID>"]; "Opt back in" removes it. Under
//    Global Privacy Control or Do Not Track, or with storage blocked, the button
//    stays hidden and the status line says why.
// 2. Loads GA4 only when every guard passes: the page is served from
//    PRODUCTION_HOST (so no local build, test run or CI job contacts Google), the
//    browser sends neither GPC nor DNT, and the reader has not opted out. Consent
//    Mode v2 defaults deny the three ad signals everywhere and deny
//    analytics_storage in the EEA, the UK and Switzerland; Google signals and ad
//    personalization are off.
//
// A question typed into the reference is never part of any address, so GA never
// sees it. The page address sent is the origin and path plus any utm_* campaign
// parameters; a referrer from another site is sent as its origin only.
(function () {
  "use strict";

  var MEASUREMENT_ID = "G-GS5D3FB3XL";
  var PRODUCTION_HOST = "sprout.chelseakr.com";
  // Renaming this key would silently opt every opted-out reader back in.
  var OPT_OUT_KEY = "sprout:analytics-opt-out";
  // The 27 EU member states, Iceland, Liechtenstein, Norway, the UK, Switzerland.
  var DENIED_REGIONS = [
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    "IS", "LI", "NO", "GB", "CH"
  ];
  var MESSAGES = {
    optedOut:
      "Opted out. From the next page you open, this site will not load Google Analytics in this browser.",
    isOut: "You have opted out: this site does not load Google Analytics in this browser.",
    backIn: "Opted back in. Analytics resumes from the next page you open.",
    signal: "Analytics is off: your browser sends Global Privacy Control or Do Not Track.",
    noStorage:
      "This browser is blocking site storage, so an opt-out cannot be remembered here. " +
      "Global Privacy Control or Do Not Track keeps analytics off."
  };

  var w = window;
  var n = navigator;
  var d = document;

  var store = null;
  try {
    store = w.localStorage;
    store.getItem(OPT_OUT_KEY);
  } catch (_error) {
    store = null;
  }

  function optedOut() {
    try {
      return Boolean(store) && store.getItem(OPT_OUT_KEY) === "1";
    } catch (_error) {
      return false;
    }
  }

  var dnt = n.doNotTrack || w.doNotTrack || n.msDoNotTrack;
  var signal = n.globalPrivacyControl === true || dnt === "1" || dnt === "yes";

  function wireChoice() {
    var box = d.querySelector("[data-analytics-choice]");
    if (!box || !MEASUREMENT_ID) return;
    var button = box.querySelector("button");
    var status = box.querySelector("[role=status]");
    function render(message) {
      button.textContent = optedOut() ? "Opt back in" : "Opt out of analytics";
      button.hidden = signal || !store;
      status.textContent = message;
      box.hidden = false;
    }
    button.addEventListener("click", function () {
      try {
        if (optedOut()) {
          store.removeItem(OPT_OUT_KEY);
          w["ga-disable-" + MEASUREMENT_ID] = false;
          render(MESSAGES.backIn);
        } else {
          store.setItem(OPT_OUT_KEY, "1");
          w["ga-disable-" + MEASUREMENT_ID] = true;
          render(MESSAGES.optedOut);
        }
      } catch (_error) {
        store = null;
        render(MESSAGES.noStorage);
      }
    });
    render(signal ? MESSAGES.signal : !store ? MESSAGES.noStorage : optedOut() ? MESSAGES.isOut : "");
  }

  if (d.readyState === "loading") d.addEventListener("DOMContentLoaded", wireChoice);
  else wireChoice();

  function scrubbedLocation() {
    var kept = [];
    var query = w.location.search.replace(/^\?/, "");
    if (query) {
      query.split("&").forEach(function (pair) {
        if (/^utm_(?:source|medium|campaign|term|content|id)=/.test(pair)) kept.push(pair);
      });
    }
    return w.location.origin + w.location.pathname + (kept.length ? "?" + kept.join("&") : "");
  }

  function scrubbedReferrer() {
    var referrer = d.referrer;
    if (!referrer) return "";
    var match = /^(https?:\/\/[^/?#]+)([^?#]*)/.exec(referrer);
    if (!match) return "";
    return match[1] === w.location.origin ? match[1] + match[2] : match[1] + "/";
  }

  if (!MEASUREMENT_ID) return;
  if (w.location.hostname !== PRODUCTION_HOST) return;
  if (n.globalPrivacyControl === true) return;
  if (dnt === "1" || dnt === "yes") return;
  if (optedOut()) return;

  w.dataLayer = w.dataLayer || [];
  function gtag() {
    w.dataLayer.push(arguments);
  }
  gtag("consent", "default", {
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
    analytics_storage: "denied",
    region: DENIED_REGIONS
  });
  gtag("consent", "default", {
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
    analytics_storage: "granted"
  });
  gtag("js", new Date());
  gtag("config", MEASUREMENT_ID, {
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
    page_location: scrubbedLocation(),
    page_referrer: scrubbedReferrer()
  });
  var script = d.createElement("script");
  script.async = true;
  script.src = "https://www.googletagmanager.com/gtag/js?id=" + MEASUREMENT_ID;
  d.head.appendChild(script);
})();
