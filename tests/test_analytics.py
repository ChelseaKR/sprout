"""Google Analytics 4 on the published site.

See docs/adr/0023-google-analytics-4-on-the-published-site.md.

Absent with no ID, silent off the production host and under GPC, DNT or the footer opt-out,
configured exactly as decided everywhere else, and on every page of both builds that make up
the site: the reference (``web-static/public/index.html``) and the handbook, through
``docs_hooks/analytics.py``.

The loader is run, not grepped. ``web-static/public/analytics.js`` executes in Node against
stubbed ``window``, ``navigator``, ``document`` and ``localStorage``, because a string search
over a script cannot show what the script does. Locally those tests skip when Node is missing;
in CI (``CI`` set) a missing Node is a failure, so the gate cannot pass by never running them.
Every negative control asserts its sabotage landed (the guard occurred exactly once and is gone
from the sabotaged copy) before asserting the harness caught it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
LOADER = ROOT / "web-static" / "public" / "analytics.js"
REFERENCE = ROOT / "web-static" / "public" / "index.html"
MEASUREMENT_ID = "G-GS5D3FB3XL"
HOST = "sprout.chelseakr.com"
KEY = "sprout:analytics-opt-out"
DENIED_REGIONS = [
    *("AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE"),
    *("IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"),
    *("IS", "LI", "NO", "GB", "CH"),
]

_HOOK = importlib.util.spec_from_file_location(
    "analytics_hook", ROOT / "docs_hooks" / "analytics.py"
)
assert _HOOK is not None and _HOOK.loader is not None
hook = importlib.util.module_from_spec(_HOOK)
_HOOK.loader.exec_module(hook)

Run = Callable[..., dict[str, Any]]


def _loader() -> str:
    return LOADER.read_text(encoding="utf-8")


def _squash(text: str) -> str:
    return " ".join(text.split())


# --- configuration and the pages ---


def test_the_committed_id_host_and_key_are_the_decided_ones() -> None:
    source = _loader()
    assert f'var MEASUREMENT_ID = "{MEASUREMENT_ID}";' in source
    assert f'var PRODUCTION_HOST = "{HOST}";' in source
    assert f'var OPT_OUT_KEY = "{KEY}";' in source


def test_the_reference_page_loads_the_loader_in_head_and_carries_the_footer_control() -> None:
    html = REFERENCE.read_text(encoding="utf-8")
    head, _, body = html.partition("</head>")
    assert head.count('<script src="analytics.js"></script>') == 1
    assert "analytics.js" not in body
    footer = re.search(r"<footer.*?</footer>", body, re.DOTALL)
    assert footer is not None
    assert footer.group(0).count("data-analytics-choice") == 1
    assert '<a href="/privacy/">' in footer.group(0)
    # The disclosure is the hook's sentence, word for word, so the two surfaces agree.
    assert hook.NOTE in _squash(footer.group(0))
    assert "googletagmanager" not in html


def test_the_hook_adds_the_loader_and_footer_to_a_handbook_page() -> None:
    page = (
        "<!doctype html><html><head><title>t</title></head><body><main>m</main>"
        '<footer class="md-footer"><div class="md-copyright">c</div></footer></body></html>'
    )
    out = hook.add_analytics(page)
    head, _, body = out.partition("</head>")
    assert head.endswith(hook.LOADER)
    assert body.count("data-analytics-choice") == 1
    assert body.index("data-analytics-choice") < body.index("</footer>")
    assert '<a href="/privacy/">' in body
    assert hook.add_analytics(out) == out  # idempotent
    assert hook.on_post_page(page, None, None) == out


@pytest.mark.parametrize(
    "page", ["<html><body><footer></footer></body></html>", "<html><head></head><body></body>"]
)
def test_the_hook_refuses_a_page_it_cannot_place_both_halves_on(page: str) -> None:
    with pytest.raises(ValueError, match="no </head> or no </footer>"):
        hook.add_analytics(page)


def test_mkdocs_registers_the_hook_the_stylesheet_and_the_privacy_page() -> None:
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    assert "docs_hooks/analytics.py" in config["hooks"]
    assert "assets/analytics.css" in config["extra_css"]
    assert {"Privacy": "privacy.md"} in config["nav"]
    assert (ROOT / "docs" / "assets" / "analytics.css").is_file()


def test_the_privacy_page_describes_ga_in_english_and_spanish() -> None:
    text = _squash((ROOT / "docs" / "privacy.md").read_text(encoding="utf-8"))
    for fact in (
        "Google Analytics 4",
        "Global Privacy Control",
        "Do Not Track",
        "Opt out of analytics",
        "Opt back in",
        KEY,
        "_ga",
        "two years",
        "cookieless",
        "Switzerland",
        "14 months",
        "Google signals and ad personalization are off",
        "A question you type into the reference",
    ):
        assert fact in text, fact
    spanish = text.split("## En español", 1)[1]
    for fact in ("Suiza", "14 meses", "sin cookies", "nunca se envía a Google", KEY):
        assert fact in spanish, fact


def test_hidden_wins_over_the_shared_button_display() -> None:
    """The shared stylesheet gives every ``button`` ``display: inline-flex``, which beats the
    browser's own rule for ``hidden``; without the restated rule the button the loader hides
    under GPC or DNT would stay on screen."""
    shared = (ROOT / "web" / "dist" / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"button\s*\{[^}]*display:\s*inline-flex", shared)
    assert "button.analytics-toggle[hidden] { display: none; }" in shared
    handbook = (ROOT / "docs" / "assets" / "analytics.css").read_text(encoding="utf-8")
    assert ".analytics-toggle[hidden]" in handbook


def test_the_offline_shell_does_not_cache_the_loader() -> None:
    worker = (ROOT / "web-static" / "public" / "service-worker.js").read_text(encoding="utf-8")
    assert "analytics.js" not in worker


# --- the loader, run in Node ---

HARNESS = r"""
const fs = require("fs");
const sc = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const code = fs.readFileSync(process.argv[3], "utf8");
const appended = [];
const listeners = {};
const data = Object.assign({}, sc.storage || {});
const blocked = () => { throw new Error("storage blocked"); };
const storage = sc.storageThrows
  ? { getItem: blocked, setItem: blocked, removeItem: blocked }
  : {
      getItem: (k) => (Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null),
      setItem: (k, v) => { data[k] = String(v); },
      removeItem: (k) => { delete data[k]; },
    };
const button = {
  hidden: true,
  textContent: "Opt out of analytics",
  onclick: null,
  addEventListener(t, f) { if (t === "click") this.onclick = f; },
};
const status = { textContent: "" };
const box = { hidden: true, querySelector: (s) => (s === "button" ? button : status) };
const document = {
  readyState: "loading",
  referrer: sc.referrer || "",
  head: { appendChild: (e) => appended.push(e) },
  createElement: (tag) => ({ tagName: tag, async: false, src: "" }),
  addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
  querySelector: (s) => (s === "[data-analytics-choice]" ? box : null),
};
const navigator = Object.assign({}, sc.navigator || {});
const url = new URL(sc.url || "https://sprout.chelseakr.com/");
const window = {
  location: {
    hostname: url.hostname, origin: url.origin, pathname: url.pathname, search: url.search,
  },
};
if (sc.windowDoNotTrack !== undefined) window.doNotTrack = sc.windowDoNotTrack;
Object.defineProperty(window, "localStorage", {
  get() { if (sc.storageGetterThrows) throw new Error("denied"); return storage; },
});
new Function("window", "navigator", "document", code)(window, navigator, document);
const snap = () => ({
  box: !box.hidden, button: !button.hidden, text: button.textContent, status: status.textContent,
  stored: Object.assign({}, data), disabled: window[sc.gaDisable] === true,
});
const states = [];
if (sc.domReady) {
  (listeners.DOMContentLoaded || []).forEach((f) => f());
  states.push(snap());
  for (let i = 0; i < (sc.clicks || 0); i++) { button.onclick(); states.push(snap()); }
}
const plain = (x) => (x instanceof Date ? "<date>" : x);
process.stdout.write(JSON.stringify({
  dataLayer: window.dataLayer ? window.dataLayer.map((a) => Array.from(a).map(plain)) : null,
  appended: appended.map((e) => ({ tag: e.tagName, async: e.async, src: e.src })),
  states,
}));
"""


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("Node is required in CI to run the GA4 loader's behavior tests")
        pytest.skip("Node is not installed; the loader's behavior tests need it")
    return node


@pytest.fixture
def run(tmp_path: Path) -> Iterator[Run]:
    node = _node()
    harness = tmp_path / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    counter = iter(range(1000))

    def _run(source: str | None = None, **scenario: Any) -> dict[str, Any]:
        index = next(counter)
        script = tmp_path / f"loader-{index}.js"
        script.write_text(_loader() if source is None else source, encoding="utf-8")
        scenario.setdefault("gaDisable", f"ga-disable-{MEASUREMENT_ID}")
        spec = tmp_path / f"scenario-{index}.json"
        spec.write_text(json.dumps(scenario), encoding="utf-8")
        # A fixed local node binary and files this test wrote.
        done = subprocess.run(
            [node, str(harness), str(spec), str(script)],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        result: dict[str, Any] = json.loads(done.stdout)
        return result

    yield _run


def _loaded(result: dict[str, Any]) -> bool:
    return result["dataLayer"] is not None or bool(result["appended"])


NOTHING_LOADS: dict[str, dict[str, Any]] = {
    "another host": {"url": "https://chelseakr.github.io/sprout/"},
    "localhost": {"url": "http://localhost:8000/"},
    "127.0.0.1": {"url": "http://127.0.0.1:8000/ARCHITECTURE/"},
    "GPC": {"navigator": {"globalPrivacyControl": True}},
    "navigator.doNotTrack": {"navigator": {"doNotTrack": "1"}},
    "window.doNotTrack": {"windowDoNotTrack": "1"},
    "navigator.msDoNotTrack": {"navigator": {"msDoNotTrack": "1"}},
    'doNotTrack "yes"': {"navigator": {"doNotTrack": "yes"}},
    "opted out": {"storage": {KEY: "1"}},
}


@pytest.mark.parametrize("case", sorted(NOTHING_LOADS))
def test_nothing_loads_off_host_under_gpc_or_dnt_or_opted_out(run: Run, case: str) -> None:
    result = run(**NOTHING_LOADS[case])
    assert result["dataLayer"] is None
    assert result["appended"] == []


def test_on_the_production_host_ga_loads_with_the_decided_configuration(run: Run) -> None:
    result = run(
        url=f"https://{HOST}/audits/eval-report/?utm_source=news&x=1#scores",
        referrer="https://www.example.org/some/path?q=who",
    )
    assert result["appended"] == [
        {
            "tag": "script",
            "async": True,
            "src": f"https://www.googletagmanager.com/gtag/js?id={MEASUREMENT_ID}",
        }
    ]
    denied_ads = {"ad_storage": "denied", "ad_user_data": "denied", "ad_personalization": "denied"}
    assert result["dataLayer"] == [
        [
            "consent",
            "default",
            {**denied_ads, "analytics_storage": "denied", "region": DENIED_REGIONS},
        ],
        ["consent", "default", {**denied_ads, "analytics_storage": "granted"}],
        ["js", "<date>"],
        [
            "config",
            MEASUREMENT_ID,
            {
                "allow_google_signals": False,
                "allow_ad_personalization_signals": False,
                "page_location": f"https://{HOST}/audits/eval-report/?utm_source=news",
                "page_referrer": "https://www.example.org/",
            },
        ],
    ]


@pytest.mark.parametrize(
    "scenario",
    [
        {"storage": {KEY: "0"}},
        {"storage": {"some-other-site:analytics-opt-out": "1"}},
        {"storageThrows": True},
        {"storageGetterThrows": True},
        {"navigator": {"doNotTrack": "0", "globalPrivacyControl": False}},
    ],
)
def test_anything_short_of_a_real_signal_or_opt_out_still_loads(
    run: Run, scenario: dict[str, Any]
) -> None:
    assert _loaded(run(**scenario))


def test_the_footer_control_opts_out_and_back_in_and_is_remembered(run: Run) -> None:
    first, out, back = run(domReady=True, clicks=2)["states"]
    assert first == {
        "box": True,
        "button": True,
        "text": "Opt out of analytics",
        "status": "",
        "stored": {},
        "disabled": False,
    }
    assert out["text"] == "Opt back in"
    assert out["stored"] == {KEY: "1"}
    assert out["disabled"] is True
    assert out["status"].startswith("Opted out.")
    assert back["text"] == "Opt out of analytics"
    assert back["stored"] == {}
    assert back["status"].startswith("Opted back in.")
    later = run(domReady=True, storage={KEY: "1"})
    assert not _loaded(later)
    assert later["states"][0]["text"] == "Opt back in"
    assert later["states"][0]["status"].startswith("You have opted out")


def test_the_footer_control_is_wired_off_the_production_host_too(run: Run) -> None:
    result = run(url="http://127.0.0.1:8000/", domReady=True, clicks=1)
    assert not _loaded(result)
    assert result["states"][1]["stored"] == {KEY: "1"}


@pytest.mark.parametrize(
    ("scenario", "starts"),
    [
        ({"navigator": {"globalPrivacyControl": True}}, "Analytics is off"),
        ({"windowDoNotTrack": "1"}, "Analytics is off"),
        ({"storageThrows": True}, "This browser is blocking site storage"),
    ],
)
def test_under_a_signal_or_blocked_storage_the_button_is_hidden_and_says_why(
    run: Run, scenario: dict[str, Any], starts: str
) -> None:
    state = run(domReady=True, **scenario)["states"][0]
    assert state["box"] is True
    assert state["button"] is False
    assert state["status"].startswith(starts)


# --- negative controls: the harness must see each guard go missing ---

SABOTAGE: dict[str, tuple[str, dict[str, Any]]] = {
    "hostname": (
        "  if (w.location.hostname !== PRODUCTION_HOST) return;\n",
        {"url": "http://127.0.0.1:8000/"},
    ),
    "GPC": (
        "  if (n.globalPrivacyControl === true) return;\n",
        {"navigator": {"globalPrivacyControl": True}},
    ),
    "DNT": ('  if (dnt === "1" || dnt === "yes") return;\n', {"navigator": {"doNotTrack": "1"}}),
    "opt-out": ("  if (optedOut()) return;\n", {"storage": {KEY: "1"}}),
}


@pytest.mark.parametrize("guard", sorted(SABOTAGE))
def test_negative_control_removing_a_guard_is_caught(run: Run, guard: str) -> None:
    line, scenario = SABOTAGE[guard]
    source = _loader()
    assert source.count(line) == 1, f"the {guard} guard is not in the loader to remove"
    broken = source.replace(line, "", 1)
    assert broken != source and line not in broken  # the sabotage landed
    assert not _loaded(run(**scenario)), "the intact loader should load nothing here"
    assert _loaded(run(broken, **scenario)), f"removing the {guard} guard went unnoticed"


def test_negative_control_sending_the_raw_address_is_caught(run: Run) -> None:
    source = _loader()
    call = "    page_location: scrubbedLocation(),\n"
    assert source.count(call) == 1
    raw = "    page_location: w.location.origin + w.location.pathname + w.location.search,\n"
    broken = source.replace(call, raw, 1)
    assert broken != source
    url = f"https://{HOST}/?q=my+cat+ate+a+pothos"
    assert run(url=url)["dataLayer"][-1][2]["page_location"] == f"https://{HOST}/"
    assert run(broken, url=url)["dataLayer"][-1][2]["page_location"] == url
