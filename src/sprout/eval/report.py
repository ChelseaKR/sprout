"""Render the eval run as committed artifacts — and self-check the HTML for a11y.

Every artifact is a pure function of the :class:`RunResult` (no wall-clock), so identical
inputs produce byte-identical files. The Markdown report is the human-facing scoreboard; the
HTML report is structurally accessibility-checked before it is written (we never emit an
inaccessible accessibility tool); JUnit and SARIF let any CI annotate failures; the model
card states limits plainly. Failures are shown, never hidden.
"""

from __future__ import annotations

import html
import json
import xml.sax.saxutils as sax
from collections.abc import Sequence
from pathlib import Path

from ..a11y import assert_accessible
from .history import HistoryEntry
from .runner import RunResult
from .suite import SuiteResult, Verdict

_DISCLAIMER = (
    "This is a build artifact from a reference implementation over a synthetic, CC0 corpus. "
    "A passing evaluation is NOT a blanket safety guarantee. This is not veterinary advice."
)


def _verdict_label(v: Verdict) -> str:
    return "✅ PASS" if v is Verdict.PASS else "❌ FAIL"


# --- JSON (canonical) ------------------------------------------------------------
def render_json(result: RunResult) -> str:
    return result.model_dump_json(indent=2)


# --- Markdown --------------------------------------------------------------------
def _suite_md(s: SuiteResult) -> str:
    direction = "higher is better" if s.metric.higher_is_better else "lower is better"
    lines = [
        f"### `{s.suite}` — {_verdict_label(s.verdict)}",
        "",
        f"- **Metric:** {s.metric.name}",
        f"- **Definition:** {s.metric.definition}",
        f"- **Score:** {s.score:.3f} (threshold {s.metric.threshold:.3f}, {direction})",
        f"- **95% CI (gated rate):** [{s.ci_low:.3f}, {s.ci_high:.3f}]"
        + ("  ⚠️ under-powered (n<30)" if s.underpowered else ""),
        f"- **Items evaluated:** {s.n_items}",
        f"- **Judge:** {s.judge_method} (config `{s.judge_config_hash[:12]}`)",
    ]
    if s.notes:
        lines.append(f"- **Notes:** {s.notes}")
    if s.segments:
        lines += ["", "| Segment | Score | n | Verdict |", "|---|---|---|---|"]
        lines += [
            f"| {seg.label} | {seg.score:.3f} | {seg.n} | {_verdict_label(seg.verdict)} |"
            for seg in s.segments
        ]
    if s.failing_examples:
        lines += ["", "<details><summary>Failing examples</summary>", ""]
        lines += [f"- `{o.item_id}` (score {o.score:.2f}): {o.detail}" for o in s.failing_examples]
        lines += ["", "</details>"]
    return "\n".join(lines)


def render_markdown(result: RunResult, history: Sequence[HistoryEntry] = ()) -> str:
    fp = result.fingerprint
    board = ["| Suite | Verdict | Score | Threshold | n |", "|---|---|---|---|---|"]
    board += [
        f"| `{s.suite}` | {_verdict_label(s.verdict)} | {s.score:.3f} "
        f"| {s.metric.threshold:.3f} | {s.n_items} |"
        for s in result.suite_results
    ]
    suites = "\n\n".join(_suite_md(s) for s in result.suite_results)
    sections = [
        "# Sprout Evaluation Report",
        "",
        f"**Overall verdict:** {_verdict_label(result.overall_verdict)}",
        "",
        "| | |",
        "|---|---|",
        f"| Run fingerprint | `{fp.digest[:16]}` |",
        f"| Harness version | {fp.harness_version} |",
        f"| Seed | {fp.seed} |",
        f"| Dataset hash | `{fp.dataset_hash[:16]}` |",
        f"| Judge config hash | `{fp.judge_config_hash[:12]}` |",
        f"| Target (answer model) | {fp.target} |",
        f"| Suites | {', '.join(fp.suite_names)} |",
        "",
        f"> {_DISCLAIMER}",
        "",
        "## Scoreboard",
        "",
        *board,
        "",
        "## Suites",
        "",
        suites,
        "",
    ]
    if history:
        sections += ["## Score trend across releases", "", render_trend_markdown(history), ""]
    return "\n".join(sections)


# --- score trend across releases --------------------------------------------------
# The trend is *not* part of RunResult, so it is deliberately kept out of render_markdown's
# and render_html's default signature — passing ``history`` is opt-in and additive, so the
# byte-identical-for-identical-inputs property of a bare `RunResult` render is unaffected.
_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


def _sparkline(scores: Sequence[float]) -> str:
    """A compact text sparkline; degrades to a flat line for a single point or no spread."""
    if not scores:
        return ""
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return _SPARK_BLOCKS[0] * len(scores)
    span = hi - lo
    return "".join(
        _SPARK_BLOCKS[min(len(_SPARK_BLOCKS) - 1, int((v - lo) / span * (len(_SPARK_BLOCKS) - 1)))]
        for v in scores
    )


def render_trend_markdown(history: Sequence[HistoryEntry]) -> str:
    """Per-suite trajectory table + sparkline across every release in ``history``."""
    if not history:
        return "_No release history recorded yet._"
    suite_names = sorted({s.suite for entry in history for s in entry.suites})
    lines = [
        f"Releases: {', '.join(e.release for e in history)}",
        "",
        "| Suite | Trend | Latest | Threshold | Releases (n) |",
        "|---|---|---|---|---|",
    ]
    for name in suite_names:
        points = [(e.release, e.score_for(name)) for e in history]
        present = [(rel, sc) for rel, sc in points if sc is not None]
        if not present:
            continue
        scores = [sc.score for _, sc in present]
        latest = present[-1][1]
        spark = _sparkline(scores)
        lines.append(
            f"| `{name}` | `{spark}` | {latest.score:.3f} "
            f"| {latest.threshold:.3f} | {len(present)} |"
        )
    lines += ["", "<details><summary>Trend data table (sparkline equivalent)</summary>", ""]
    lines += ["| Suite | Release | Date | Score | Verdict |", "|---|---|---|---|---|"]
    for entry in history:
        for s in entry.suites:
            lines.append(
                f"| `{s.suite}` | {entry.release} | {entry.recorded_date} "
                f"| {s.score:.3f} | {_verdict_label(s.verdict)} |"
            )
    lines += ["", "</details>"]
    return "\n".join(lines)


def render_trend_html(history: Sequence[HistoryEntry]) -> str:
    """Accessible trend section: an ``aria-hidden`` sparkline plus its required data-table
    equivalent (WCAG 1.1.1 non-text-content — the sparkline conveys nothing a screen-reader
    user cannot get from the table right beneath it)."""
    if not history:
        return (
            "<section><h2>Score trend across releases</h2><p>No release history yet.</p></section>"
        )
    suite_names = sorted({s.suite for entry in history for s in entry.suites})
    spark_rows = ""
    for name in suite_names:
        present = [(e, e.score_for(name)) for e in history if e.score_for(name) is not None]
        if not present:
            continue
        scores = [sc.score for _, sc in present if sc is not None]
        spark_rows += (
            f"<tr><td><code>{html.escape(name)}</code></td>"
            f'<td aria-hidden="true">{html.escape(_sparkline(scores))}</td>'
            f"<td>{scores[-1]:.3f}</td><td>{len(present)}</td></tr>"
        )
    detail_rows = "".join(
        f"<tr><td><code>{html.escape(s.suite)}</code></td><td>{html.escape(entry.release)}</td>"
        f"<td>{html.escape(entry.recorded_date)}</td><td>{s.score:.3f}</td>"
        f"<td>{'PASS' if s.verdict is Verdict.PASS else 'FAIL'}</td></tr>"
        for entry in history
        for s in entry.suites
    )
    return (
        '<section aria-labelledby="score-trend">'
        '<h2 id="score-trend">Score trend across releases</h2>'
        f"<p>Releases recorded: {html.escape(', '.join(e.release for e in history))}.</p>"
        "<table><caption>Per-suite trend (sparkline is decorative; see the data table for "
        "the same values)</caption><thead><tr>"
        '<th scope="col">Suite</th><th scope="col">Trend</th>'
        '<th scope="col">Latest score</th><th scope="col">Releases (n)</th></tr></thead>'
        f"<tbody>{spark_rows}</tbody></table>"
        "<table><caption>Trend data table — every recorded release, per suite</caption>"
        '<thead><tr><th scope="col">Suite</th><th scope="col">Release</th>'
        '<th scope="col">Date</th><th scope="col">Score</th>'
        '<th scope="col">Verdict</th></tr></thead>'
        f"<tbody>{detail_rows}</tbody></table>"
        "</section>"
    )


# --- HTML (self-a11y-checked) ----------------------------------------------------
def _suite_html(s: SuiteResult) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(o.item_id)}</td><td>{o.score:.2f}</td>"
        f"<td>{html.escape(o.detail)}</td></tr>"
        for o in s.failing_examples
    )
    failing = (
        f"<table><caption>Failing examples for {html.escape(s.suite)}</caption>"
        f'<thead><tr><th scope="col">Item</th><th scope="col">Score</th>'
        f'<th scope="col">Detail</th></tr></thead><tbody>{rows}</tbody></table>'
        if s.failing_examples
        else ""
    )
    return (
        f'<section aria-labelledby="s-{html.escape(s.suite)}">'
        f'<h3 id="s-{html.escape(s.suite)}">{html.escape(s.suite)}: '
        f"{'PASS' if s.verdict is Verdict.PASS else 'FAIL'}</h3>"
        f"<p>{html.escape(s.metric.definition)}</p>"
        f"<p>Score {s.score:.3f} (threshold {s.metric.threshold:.3f}); "
        f"95% CI [{s.ci_low:.3f}, {s.ci_high:.3f}]; n={s.n_items}.</p>{failing}</section>"
    )


def render_html(result: RunResult, history: Sequence[HistoryEntry] = ()) -> str:
    fp = result.fingerprint
    board = "".join(
        f"<tr><td><code>{html.escape(s.suite)}</code></td>"
        f"<td>{'PASS' if s.verdict is Verdict.PASS else 'FAIL'}</td>"
        f"<td>{s.score:.3f}</td><td>{s.metric.threshold:.3f}</td><td>{s.n_items}</td></tr>"
        for s in result.suite_results
    )
    suites = "".join(_suite_html(s) for s in result.suite_results)
    overall = "PASS" if result.overall_verdict is Verdict.PASS else "FAIL"
    trend = render_trend_html(history) if history else ""
    doc = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Sprout Evaluation Report</title></head><body><main>"
        "<h1>Sprout Evaluation Report</h1>"
        f"<p><strong>Overall verdict: {overall}</strong></p>"
        f"<p>Run <code>{fp.digest[:16]}</code> · harness {html.escape(fp.harness_version)} · "
        f"seed {fp.seed} · judge <code>{html.escape(fp.judge_config_hash[:12])}</code> · "
        f"target {html.escape(fp.target)}.</p>"
        f"<p>{html.escape(_DISCLAIMER)}</p>"
        "<h2>Scoreboard</h2>"
        "<table><caption>Suite results</caption><thead><tr>"
        '<th scope="col">Suite</th><th scope="col">Verdict</th><th scope="col">Score</th>'
        '<th scope="col">Threshold</th><th scope="col">Items</th></tr></thead>'
        f"<tbody>{board}</tbody></table>"
        f"<h2>Suites</h2>{suites}"
        f"{trend}"
        "</main></body></html>"
    )
    assert_accessible(doc)  # fail closed: never emit an inaccessible report
    return doc


# --- JUnit -----------------------------------------------------------------------
def render_junit(result: RunResult) -> str:
    cases = []
    failures = sum(1 for s in result.suite_results if not s.passed)
    for s in result.suite_results:
        body = ""
        if not s.passed:
            msg = sax.quoteattr(f"score {s.score:.3f} vs threshold {s.metric.threshold:.3f}")
            body = f"<failure message={msg}>{sax.escape(s.notes or s.metric.name)}</failure>"
        cases.append(
            f'<testcase classname="sprout.eval" name="{sax.escape(s.suite)}">{body}</testcase>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuites tests="{len(result.suite_results)}" failures="{failures}">'
        f'<testsuite name="sprout-eval" tests="{len(result.suite_results)}" '
        f'failures="{failures}">{"".join(cases)}</testsuite></testsuites>'
    )


# --- SARIF -----------------------------------------------------------------------
def render_sarif(result: RunResult, dataset_path: str = "eval/suites") -> str:
    rules = [
        {
            "id": f"sprout-eval/{s.suite}",
            "name": s.metric.name,
            "shortDescription": {"text": s.metric.definition},
        }
        for s in result.suite_results
    ]
    results = [
        {
            "ruleId": f"sprout-eval/{s.suite}",
            "level": "error",
            "message": {
                "text": f"{s.suite} scored {s.score:.3f} (threshold {s.metric.threshold:.3f})"
            },
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": dataset_path}}}],
        }
        for s in result.suite_results
        if not s.passed
    ]
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "sprout-eval",
                        "version": result.fingerprint.harness_version,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2, sort_keys=True)


# --- model card scoreboard -------------------------------------------------------
def render_model_card_scoreboard(result: RunResult) -> str:
    rows = "\n".join(
        f"| `{s.suite}` | {_verdict_label(s.verdict)} | {s.score:.3f} "
        f"| {s.metric.threshold:.3f} | {s.n_items} | {s.notes} |"
        for s in result.suite_results
    )
    return "\n".join(
        [
            "| Suite | Verdict | Score | Threshold | n | Notes |",
            "|---|---|---|---|---|---|",
            rows,
        ]
    )


# --- baseline diff ---------------------------------------------------------------
def diff_against_baseline(
    current: RunResult, baseline: RunResult, *, tolerance: float = 0.05
) -> list[str]:
    """Flag fingerprint mismatches, verdict flips, score erosion, and dropped suites."""
    issues: list[str] = []
    cf, bf = current.fingerprint, baseline.fingerprint
    for field in ("dataset_hash", "judge_config_hash", "seed", "target"):
        if getattr(cf, field) != getattr(bf, field):
            issues.append(f"comparability: {field} differs from baseline")
    base = {s.suite: s for s in baseline.suite_results}
    for s in current.suite_results:
        b = base.get(s.suite)
        if b is None:
            continue
        if b.passed and not s.passed:
            issues.append(f"regression: suite `{s.suite}` flipped PASS->FAIL")
        elif s.metric.higher_is_better and (b.score - s.score) > tolerance:
            issues.append(
                f"erosion: suite `{s.suite}` dropped {b.score:.3f}->{s.score:.3f} (> {tolerance})"
            )
    dropped = set(base) - {s.suite for s in current.suite_results}
    issues += [f"dropped suite `{name}`" for name in sorted(dropped)]
    return issues


def load_run_result(path: str | Path) -> RunResult:
    return RunResult.model_validate_json(Path(path).read_text(encoding="utf-8"))


# --- writer ----------------------------------------------------------------------
_RENDERERS = {
    "json": (render_json, "eval-report.json"),
    "md": (render_markdown, "eval-report.md"),
    "html": (render_html, "eval-report.html"),
    "junit": (render_junit, "eval-report.junit.xml"),
    "sarif": (render_sarif, "eval-report.sarif"),
}


def write_reports(
    result: RunResult,
    out_dir: str | Path,
    formats: tuple[str, ...] = ("json", "md", "html", "junit", "sarif"),
    history: Sequence[HistoryEntry] = (),
) -> list[Path]:
    """Write the requested report formats. ``history``, if non-empty, adds a release-trend
    section to the Markdown and HTML reports only (the other formats are CI-tool artifacts
    with no notion of "across releases")."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Always run the HTML self-a11y check, even if HTML is not among the requested
    # formats, so "we never emit an inaccessible accessibility tool" is an unconditional
    # invariant rather than a property of the default argument (render_html raises on fail).
    render_html(result, history)
    written: list[Path] = []
    for fmt in formats:
        renderer, filename = _RENDERERS[fmt]
        path = out / filename
        content = (
            renderer(result, history) if fmt in ("md", "html") else renderer(result)  # type: ignore[call-arg]
        )
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written
