"""The ``sprout`` command-line interface.

Subcommands: ``ingest`` (build the index), ``ask`` (a cited answer or honest refusal),
``serve`` (the stateless reference UI + API), ``eval`` (record the live engine, run the suites,
regenerate the committed report), ``a11y-check`` (structural WCAG gate on rendered HTML),
``freshness``
(offline citation-freshness check, opt-in link-liveness), ``claims-check`` (doc claims vs
their code/config source of truth), ``smoke`` (the Phase 1 CI smoke suite of corpus-derived
questions), ``check-tuning-scope`` (fail-closed gate for tunable-surface changes),
``calibrate`` (judge agreement + kappa), ``fit-confidence`` (re-fit the confidence logistic
on a held-out train split),
``toxicity coverage``/``toxicity check`` (the structured
per-row-cited toxicity table — coverage report and table-vs-prose consistency gate),
``corpus-report`` (EXP-12 corpus workbench),
``propose template``/``propose check`` (the SME corpus-contribution path: provenance,
corpus lint, safety, and representational-harm review of an incoming passage + eval case),
``ci-parity-check`` (mechanical `make verify` vs. `ci-gate` invocation-diff), and ``demo``
(a scripted session). Everything runs offline by default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from . import __version__
from .a11y import check_html
from .answer import Assistant
from .claims import check as check_claims
from .config import Config, load_config
from .models import Answer
from .slo import check_all

app = typer.Typer(add_completion=False, help="Sprout — grounded, evaluated plant-care assistant.")

_DEFAULT_CONFIG = "config/sprout.yaml"
ConfigOpt = Annotated[str, typer.Option("--config", help="Path to the config YAML.")]


def _load(config_path: str) -> Config:
    """Load the local config; fall back to the config bundled in the package."""
    from . import resources

    p = Path(config_path)
    if p.exists():
        return load_config(p)
    packaged = resources.packaged_config()
    return load_config(packaged) if packaged.exists() else Config()


def _target_name(cfg: Config) -> str:
    base = f"{cfg.generation.provider}:{cfg.generation.model or 'extractive'}"
    if cfg.generation.support_verifier == "nli":
        from .verifiers import config_identity

        # EXP-04: fold the entailment verifier's model/revision/weight-hash/threshold into
        # the eval fingerprint's target so an eval run with the verifier on is never
        # conflated with one where it's off (RunFingerprint hashes `target`).
        base = f"{base}+{config_identity(cfg.generation.nli)}"
    return base


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


@app.command()
def ingest(config: ConfigOpt = _DEFAULT_CONFIG) -> None:
    """Build the vector index from the bundled corpus."""
    from .ingest import ingest as run_ingest

    cfg = _load(config)
    store = run_ingest(cfg)
    typer.echo(f"Ingested {len(store)} chunks into {cfg.store.path}")


@app.command("corpus-report")
def corpus_report_cmd(
    config: ConfigOpt = _DEFAULT_CONFIG,
    out: Annotated[str, typer.Option("--out")] = "docs/audits",
    gate: Annotated[bool, typer.Option("--gate")] = False,
) -> None:
    """Species x topic x language completeness, EN/ES parity diff, chunk-quality lint.

    Maintainer tooling for safe corpus growth (EXP-12, docs/ideation/03-expansions.md):
    emits a committed matrix + parity-diff + lint report beside the eval report. Advisory
    by default (always exits 0); pass ``--gate`` to fail when any finding needs review —
    the promotion path to a merge gate once the heuristics are tuned.
    """
    from .corpus_report import build_report, render_json, render_markdown

    cfg = _load(config)
    report = build_report(cfg)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "corpus-report.md").write_text(render_markdown(report), encoding="utf-8")
    (out_dir / "corpus-report.json").write_text(render_json(report), encoding="utf-8")
    typer.echo(render_markdown(report))
    raise typer.Exit(1 if gate and not report.clean else 0)


def _print_answer_obj(answer: Answer) -> None:
    typer.echo(answer.display_text)
    if answer.context_note:
        typer.echo(f"\n{answer.context_note}")
    if answer.citations:
        typer.echo("\nSources:")
        for c in answer.citations:
            typer.echo(f"  - {c.label}")
    if answer.as_of:
        typer.echo(f"\nBased on references as of {answer.as_of}.")
    flag = " (low confidence)" if answer.low_confidence and not answer.refused else ""
    # The band word leads, the number follows — never the reverse — so a screen reader
    # or a terminal read top-to-bottom announces the calibrated language first and the
    # raw float is still there, right after it, for anyone who wants the number (EXP-06).
    typer.echo(
        f"[confidence: {answer.confidence_band_label} ({answer.confidence:.2f}){flag} · "
        f"{answer.disclosure}]"
    )


def _maybe_capture_review(cfg: Config, trace: Any) -> None:
    """Queue ``trace`` for the local review console, if opted in (EXP-17).

    Off by default (``ReviewConfig.enabled``); a maintainer must set it in
    ``config/sprout.yaml`` first. See ``docs/RESPONSIBLE-TECH-AUDITS.md`` §C and
    ``docs/adr/0020-local-review-console-for-flagged-answers.md`` before enabling --
    the queue stores question text locally, unlike the rest of Sprout's logging.

    Refusals are checked *first*: every refusal also carries ``low_confidence=True``
    (see ``Assistant._refuse``), so testing the low-confidence opt-out before the
    refusal opt-in would make ``capture_on_refusal: true`` unreachable whenever
    ``capture_on_low_confidence`` is false — the same precedence ``ReviewQueue.capture``
    uses.
    """
    if not cfg.review.enabled:
        return
    answer = trace.answer
    if answer.refused:
        if not cfg.review.capture_on_refusal:
            return
    elif answer.low_confidence and not cfg.review.capture_on_low_confidence:
        return
    from .review import ReviewQueue

    ReviewQueue(cfg.review.path, max_items=cfg.review.max_items).capture(trace)


def _print_answer(
    assistant: Assistant,
    question: str,
    language: str | None,
    debug: bool,
    cfg: Config | None = None,
    *,
    season: str | None = None,
    light: str | None = None,
) -> None:
    answer = assistant.answer(question, language, season=season, light=light)
    _print_answer_obj(answer)
    want_trace = debug or (
        cfg is not None and cfg.review.enabled and (answer.low_confidence or answer.refused)
    )
    trace = assistant.trace(question, language, season=season, light=light) if want_trace else None
    if cfg is not None and trace is not None:
        _maybe_capture_review(cfg, trace)
    if debug and trace is not None:
        typer.echo("\n--- trace ---")
        typer.echo(
            f"language={trace.language} safety={trace.is_safety_query} "
            f"injections={trace.injection_categories}"
        )
        for rc in trace.retrieved:
            typer.echo(f"  [{rc.score:.3f}] {rc.chunk.chunk_id} {rc.chunk.source}")


@app.command()
def ask(
    question: str,
    language: Annotated[str | None, typer.Option("--language", "-l")] = None,
    season: Annotated[
        str | None,
        typer.Option(
            "--season",
            help=(
                "Season as you'd say it (e.g. 'winter'). Used only to select the "
                "matching cited passage this one time — never stored, never a fact."
            ),
        ),
    ] = None,
    light: Annotated[
        str | None,
        typer.Option(
            "--light",
            help=(
                "Light/placement as you'd say it (e.g. 'low light', 'north window'). "
                "Used only to select the matching cited passage this one time — never "
                "stored, never a fact."
            ),
        ),
    ] = None,
    config: ConfigOpt = _DEFAULT_CONFIG,
    debug: Annotated[bool, typer.Option("--debug")] = False,
) -> None:
    """Answer a plant-care question from the cited corpus, or refuse honestly."""
    cfg = _load(config)
    try:
        assistant = Assistant.from_config(cfg)
    except FileNotFoundError as exc:
        typer.echo(f"{exc}", err=True)
        raise typer.Exit(2) from exc
    _print_answer(assistant, question, language, debug, cfg, season=season, light=light)


@app.command()
def serve(
    config: ConfigOpt = _DEFAULT_CONFIG,
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
) -> None:  # pragma: no cover - launches a blocking server
    """Run the accessible reference UI and JSON/SSE API."""
    import uvicorn

    from .server import create_app

    cfg = _load(config)
    uvicorn.run(create_app(cfg), host=host or cfg.server.host, port=port or cfg.server.port)


@app.command("eval")
def evaluate(
    config: ConfigOpt = _DEFAULT_CONFIG,
    suites: Annotated[str, typer.Option("--suites")] = "all",
    judge: Annotated[str, typer.Option("--judge")] = "deterministic",
    out: Annotated[str, typer.Option("--out")] = "docs/audits",
    suite_dir: Annotated[str, typer.Option("--suite-dir")] = "eval/suites",
    statistical_gate: Annotated[bool, typer.Option("--statistical-gate")] = False,
    update_baseline: Annotated[bool, typer.Option("--update-baseline")] = False,
    release: Annotated[
        str | None,
        typer.Option(
            "--release",
            help=(
                "Release identifier (e.g. a tag). When set, this run's per-suite scores are "
                "appended to <out>/eval-history.jsonl and the trend/drift gate runs. Pass this "
                "only from the release workflow — never per-PR — so the ledger stays one entry "
                "per release."
            ),
        ),
    ] = None,
    drift_k: Annotated[
        int,
        typer.Option(
            "--drift-k",
            help="Fail the release gate if any suite declined for this many consecutive "
            "releases in a row, even if each decline was inside baseline tolerance.",
        ),
    ] = 3,
) -> None:
    """Record the live engine over the cases, run the suites, regenerate the report.

    Unless ``--update-baseline`` is passed, the run is also diffed against the committed
    ``<out>/eval-baseline.json`` (fingerprint comparability, PASS->FAIL flips, and score
    erosion beyond tolerance); any issue — including a stale baseline whose fingerprint no
    longer matches this run's dataset/judge/target — fails the command even if every suite
    individually passed its own threshold.

    Also fails closed (FIX-08 / ADR-0016) if ``confidence.fit`` is recorded but no longer
    matches the live ``retrieval:`` config — a retrieval change since the fit invalidates
    its evidence scale; re-run ``sprout fit-confidence`` before trusting it again.

    With ``--release``, the run also appends to and is checked against
    ``<out>/eval-history.jsonl`` (EXP-13): a suite that declined for ``--drift-k`` consecutive
    releases fails the gate even if every one of those declines was individually within the
    baseline diff's tolerance — the ledger catches the slow bleed the one-shot diff cannot.
    """
    from .confidence import fit_drift_warning
    from .eval.dataset import load_suite_dir, write_sidecar
    from .eval.history import (
        append_history_entry,
        check_drift,
        history_entry_from_result,
        load_history,
    )
    from .eval.judge import build_judge
    from .eval.record import record
    from .eval.report import diff_against_baseline, load_run_result, render_markdown, write_reports
    from .eval.runner import run_evaluation
    from .eval.suite import resolve_suites
    from .eval.suites.refusal import threshold_for as refusal_threshold_for

    cfg = _load(config)
    drift = fit_drift_warning(cfg.confidence, cfg.retrieval)
    if drift:
        typer.echo(drift, err=True)
        raise typer.Exit(1)
    assistant = Assistant.from_config(cfg)
    dataset = load_suite_dir(suite_dir, verify_hash=not update_baseline)
    if update_baseline:
        write_sidecar(dataset, Path(suite_dir).parent / "suites.sha256")
    golden = record(assistant, dataset, cfg)
    resolved_suites = resolve_suites(suites)
    # The refusal suite's committed threshold is the offline hashing-embedder floor (0.90).
    # Once the semantic Bedrock/Titan embedding path is configured, enforce the stated
    # portfolio target (0.95) instead of silently continuing to accept the offline floor —
    # see docs/ROADMAP.md's AI evaluation suites table.
    threshold_overrides = {}
    if any(s.name == "refusal" for s in resolved_suites):
        threshold_overrides["refusal"] = refusal_threshold_for(cfg.retrieval.embedding_provider)
    result = run_evaluation(
        golden,
        build_judge(judge),
        resolved_suites,
        target=_target_name(cfg),
        statistical_gate=statistical_gate,
        threshold_overrides=threshold_overrides,
    )
    history_path = Path(out, "eval-history.jsonl")
    history = load_history(history_path)
    if release:
        entry = history_entry_from_result(result, release=release)
        append_history_entry(history_path, entry)  # idempotent per release id
        history = load_history(history_path)
    write_reports(result, out, history=history)
    typer.echo(render_markdown(result, history))
    exit_code = result.exit_code
    baseline_path = Path(out, "eval-baseline.json")
    if update_baseline:
        baseline_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    elif not _baseline_check_passes(result, baseline_path, load_run_result, diff_against_baseline):
        exit_code = 1
    if release and not _drift_check_passes(history, drift_k, check_drift):
        exit_code = 1
    raise typer.Exit(exit_code)


def _baseline_check_passes(
    result: Any, baseline_path: Path, load_run_result: Any, diff_against_baseline: Any
) -> bool:
    if not baseline_path.exists():
        typer.echo(
            f"\nNo committed baseline at {baseline_path} — skipping regression check "
            "(run `sprout eval --update-baseline` once to create it).",
            err=True,
        )
        return True
    issues = diff_against_baseline(result, load_run_result(baseline_path))
    if issues:
        typer.echo("\nBaseline regression check FAILED:", err=True)
        for issue in issues:
            typer.echo(f"  - {issue}", err=True)
        return False
    typer.echo("\nBaseline regression check: no issues.")
    return True


def _drift_check_passes(history: Any, drift_k: int, check_drift: Any) -> bool:
    drift_issues = check_drift(history, k=drift_k)
    if drift_issues:
        typer.echo("\nEval trend drift check FAILED:", err=True)
        for issue in drift_issues:
            typer.echo(f"  - {issue}", err=True)
        return False
    typer.echo(f"\nEval trend drift check ({drift_k}-release window): no issues.")
    return True


@app.command()
def smoke(
    config: ConfigOpt = _DEFAULT_CONFIG,
    out: Annotated[str, typer.Option("--out")] = "docs/audits",
    language: Annotated[str, typer.Option("--language")] = "en",
) -> None:
    """Phase 1 CI smoke suite: corpus-derived questions, no hand-authored YAML.

    One question per (species, topic) pair actually present in the ingested corpus,
    mechanically templated from the corpus's own species slugs and topic taxonomy — a
    fast, judge-free canary that fails loudly on a broken species/topic combination well
    before the heavier, hand-authored Phase 2 eval harness runs. Requires ``sprout
    ingest`` to have populated the store first.
    """
    from .smoke import run_smoke, to_markdown
    from .store import VectorStore

    cfg = _load(config)
    try:
        store = VectorStore.load(cfg.store.path)
    except FileNotFoundError as exc:
        typer.echo(f"{exc} (run `sprout ingest` first)", err=True)
        raise typer.Exit(2) from exc
    assistant = Assistant.from_store(cfg, store)
    result = run_smoke(assistant, store, cfg, language=language)

    report = to_markdown(result)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "smoke-report.md").write_text(report, encoding="utf-8")

    typer.echo(report)
    if not result.passed:
        raise typer.Exit(1)


@app.command("check-tuning-scope")
def check_tuning_scope_cmd(
    base: Annotated[
        str, typer.Option("--base", help="Git ref this branch is diffed against.")
    ] = "origin/main",
    head: Annotated[str, typer.Option("--head")] = "HEAD",
    baseline: Annotated[
        str, typer.Option("--baseline", help="Committed eval baseline to verify ids against.")
    ] = "docs/audits/eval-baseline.json",
) -> None:
    """Fail if this change tunes retrieval/prompts/guards without citing an already-committed
    eval failure (ROADMAP Phase 3: tune only against committed failures, never the held-out set).

    No-op when the diff does not semantically change the tunable surface. Comment-only YAML and
    the exact named lifecycle wrapper around an otherwise-identical provider constructor are
    compared mechanically and excluded. The initial lifecycle module is admitted once by its
    reviewed digest; later lifecycle and unknown provider hunks fail closed. Otherwise the commit
    range must carry a ``Tunes-Against: <case-id>[, <case-id>...]`` trailer whose ids already
    appear in the merge-base commit's ``<baseline>`` ``failing_examples``.
    """
    from .eval.tuning_scope import TuningScopeError, check_tuning_scope

    try:
        issues = check_tuning_scope(base_ref=base, head_ref=head, baseline_path=baseline)
    except TuningScopeError as exc:
        typer.echo(f"Tuning-scope check could not run: {exc}", err=True)
        raise typer.Exit(2) from exc
    if issues:
        typer.echo("Tuning-scope check FAILED:", err=True)
        for issue in issues:
            typer.echo(f"  - {issue}", err=True)
        raise typer.Exit(1)
    typer.echo(
        "Tuning-scope check: no tunable-surface change, or all changes cite committed eval "
        "failures."
    )


@app.command("a11y-check")
def a11y_check(
    path: Annotated[str, typer.Argument()] = "docs/audits/eval-report.html",
) -> None:
    """Run the structural WCAG gate on a rendered HTML file."""
    target = Path(path)
    if not target.exists():
        typer.echo(f"file not found: {target}", err=True)
        raise typer.Exit(2)
    problems = check_html(target.read_text(encoding="utf-8"))
    if problems:
        for p in problems:
            typer.echo(f"  - {p}", err=True)
        raise typer.Exit(1)
    typer.echo(f"{target}: no structural accessibility violations")


@app.command("freshness")
def freshness_check(
    config: ConfigOpt = _DEFAULT_CONFIG,
    check_links: Annotated[
        bool,
        typer.Option(
            "--check-links",
            help="Also HEAD/GET every cited URL (network, opt-in; off by default).",
        ),
    ] = False,
) -> None:
    """Flag stale ``fetch_date``s (stricter for toxicity citations); optionally check links.

    Offline and deterministic by default: only parses the manifest against today's date.
    ``--check-links`` additionally fetches every cited URL over the network (skipping the
    synthetic corpus's ``example.invalid`` host) to catch dead or redirected citations.
    """
    from datetime import date

    from . import resources
    from .freshness import check_freshness, check_liveness, summarize
    from .ingest import load_manifest

    cfg = _load(config)
    manifest = load_manifest(resources.locate(cfg.corpus.manifest))
    findings = check_freshness(
        manifest,
        today=date.today(),
        max_age_days=cfg.corpus.freshness.max_age_days,
        toxicity_max_age_days=cfg.corpus.freshness.toxicity_max_age_days,
    )
    if check_links:
        findings = findings + check_liveness(manifest)

    if not findings:
        typer.echo("freshness: no stale or dead citations found")
        raise typer.Exit(0)

    for f in findings:
        typer.echo(f"  - [{f.severity}] {f.file} ({f.url}): {f.reason}", err=True)
    counts = summarize(findings)
    typer.echo(f"freshness: {counts['high']} high, {counts['warning']} warning", err=True)
    raise typer.Exit(1 if counts["high"] else 0)


@app.command("claims-check")
def claims_check(
    path: Annotated[str, typer.Argument()] = "docs/claims.yaml",
) -> None:
    """Check every registered doc claim against its code/config source of truth."""
    target = Path(path)
    if not target.exists():
        typer.echo(f"file not found: {target}", err=True)
        raise typer.Exit(2)
    problems = check_claims(target)
    if problems:
        for p in problems:
            typer.echo(f"  - {p}", err=True)
        raise typer.Exit(1)
    typer.echo(f"{target}: all claims reconciled with their source of truth")


@app.command("slo-check")
def slo_check(
    slo_dir: Annotated[str, typer.Option("--slo-dir")] = "slos",
    alerts_dir: Annotated[str, typer.Option("--alerts-dir")] = "alerts",
) -> None:
    """Schema-check the Tier-A SLO and burn-rate-alert files (STANDARDS/OBSERVABILITY-
    STANDARD.md §§4-5): every ``slos/*.yaml`` has the five required keys, every
    ``alerts/*.yml`` rule is a well-formed record/alert with an expr, and each SLO has
    both a critical and a high burn-rate alert defined. Complements, but does not
    replace, ``promtool check rules`` (see docstring in ``sprout.slo``)."""
    problems = check_all(Path(slo_dir), Path(alerts_dir))
    if problems:
        for p in problems:
            typer.echo(f"  - {p}", err=True)
        raise typer.Exit(1)
    typer.echo(f"{slo_dir}/ and {alerts_dir}/: all SLO/alert files valid")


@app.command()
def calibrate(
    probes: Annotated[str, typer.Argument()] = "eval/judge_probes.yaml",
    judge: Annotated[str, typer.Option("--judge")] = "deterministic",
    out: Annotated[str, typer.Option("--out")] = "docs/audits",
    gate: Annotated[bool, typer.Option("--gate")] = False,
) -> None:
    """Calibrate the judge against human-labeled probes (agreement + Cohen's kappa).

    Reports by default (exit 0); pass ``--gate`` to fail when below threshold. CI runs
    the offline deterministic judge with ``--gate`` (P0-4: with the negation/antonym
    polarity guard it clears the threshold; 66 labeled probes as of 2026-07-08) as a
    regression smoke-floor — it catches gross coverage/negation/polarity breakage, not a
    certification of human-level semantic judgment (morphological synonyms and low-overlap
    paraphrase remain documented blind spots; see the disagreements list in the report).
    Re-gate the calibrated LLM judge (``--judge llm --gate``, run with live credentials
    outside CI — the LLM judge is never hit in CI) before it backs a production run.

    Also warns (does not yet fail — AIEV-20, tied to the P0-4 remediation) when the probe
    set's ``labeled_date`` is more than 30 days old, per the ROADMAP "judge-calibration
    freshness" row.
    """
    from datetime import date

    from .eval.calibration import JudgeProbe, to_markdown
    from .eval.calibration import calibrate as run_calibrate
    from .eval.judge import build_judge

    raw = yaml.safe_load(Path(probes).read_text(encoding="utf-8"))
    labeled_date = raw.get("labeled_date") if isinstance(raw, dict) else None
    if labeled_date:
        age_days = (date.today() - date.fromisoformat(str(labeled_date))).days
        if age_days > 30:
            typer.echo(
                f"warning: probe set labeled_date {labeled_date} is {age_days} days old "
                "(> 30-day freshness target); re-label before trusting this record.",
                err=True,
            )
    else:
        typer.echo(
            f"warning: {probes} has no labeled_date field; cannot check calibration-probe "
            "freshness.",
            err=True,
        )
    items = [JudgeProbe.model_validate(p) for p in (raw.get("probes", raw))]
    record = run_calibrate(build_judge(judge), items)
    out_dir = Path(out)
    out_dir.mkdir(
        parents=True, exist_ok=True
    )  # match eval's write_reports; --out may not exist yet
    (out_dir / "judge-calibration.json").write_text(record.model_dump_json(indent=2), "utf-8")
    (out_dir / "judge-calibration.md").write_text(to_markdown(record), encoding="utf-8")
    typer.echo(
        f"agreement={record.agreement:.3f} kappa={record.cohens_kappa:.3f} "
        f"meets_threshold={record.meets_threshold}"
    )
    raise typer.Exit(1 if gate and not record.meets_threshold else 0)


@app.command("ci-parity-check")
def ci_parity_check(
    workflow: Annotated[str, typer.Option("--workflow")] = ".github/workflows/ci.yml",
    makefile: Annotated[str, typer.Option("--makefile")] = "Makefile",
) -> None:
    """Mechanically diff `make verify`'s commands against the required `ci-gate` jobs.

    Fails if a CI job required by `ci-gate` runs a command `make verify` doesn't (drift the
    other direction is also reported), except for the small documented allowlist in
    `sprout.ci_parity` (packaging smoke-build, environment sync, and gitleaks — which CI
    runs as an Action, not a shell command).
    """
    from .ci_parity import check_parity, format_reports

    workflow_path, makefile_path = Path(workflow), Path(makefile)
    for p in (workflow_path, makefile_path):
        if not p.exists():
            typer.echo(f"file not found: {p}", err=True)
            raise typer.Exit(2)
    reports = check_parity(workflow_path, makefile_path)
    typer.echo(format_reports(reports))
    if not all(r.ok for r in reports):
        raise typer.Exit(1)


@app.command("gate-inventory")
def gate_inventory(
    roadmap: Annotated[str, typer.Option("--roadmap")] = "docs/ROADMAP.md",
    out: Annotated[str, typer.Option("--out")] = "docs/audits",
    gate: Annotated[bool, typer.Option("--gate")] = True,
) -> None:
    """Regenerate the gate-inventory audit: every ledger AUTO row -> its enforcement mechanism.

    Fails (exit 1) by default when any ``AUTO`` row in ``docs/ROADMAP.md`` cannot be
    mechanically resolved to a real Makefile target, CI step, or repo file — the FIX-02
    "mechanical spine" that catches a ledger claiming enforcement nothing wires. Pass
    ``--no-gate`` to just regenerate the report without failing.
    """
    from .gate_inventory import build_inventory, render_markdown, unresolved_auto_rows

    resolutions = build_inventory(Path(roadmap), Path("."))
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = render_markdown(resolutions)
    (out_dir / "gate-inventory.md").write_text(report, encoding="utf-8")
    unresolved = unresolved_auto_rows(resolutions)
    typer.echo(report)
    if unresolved:
        typer.echo(
            f"\n{len(unresolved)} declared-but-unenforced AUTO row(s):",
            err=True,
        )
        for r in unresolved:
            typer.echo(f"  - {r.row.metric}: {r.detail}", err=True)
    raise typer.Exit(1 if gate and unresolved else 0)


@app.command("fit-confidence")
def fit_confidence_cmd(
    train: Annotated[
        str, typer.Option("--train", help="Held-out train split (never eval/suites/).")
    ] = "eval/train/calibration_train.yaml",
    config: ConfigOpt = _DEFAULT_CONFIG,
) -> None:
    """Fit ``confidence.fit``'s midpoint/steepness/margin_bonus on a held-out train split.

    Replays the live engine over ``--train`` (default ``eval/train/calibration_train.yaml``
    -- deliberately never a file under ``eval/suites/``: fitting against the eval set would
    make the calibration suite's ECE gate a check of nothing) and grid-fits the same
    3-parameter logistic ``confidence.py`` already uses. Writes the fitted constants plus
    provenance (train-dataset hash, retrieval-config hash, item count, date) into
    ``confidence.fit`` in ``--config``, so the next ``sprout eval`` run uses them (FIX-08,
    ADR-0016). The write is a targeted text edit that preserves every other line of the
    config file, including its hand-written comments.
    """
    from .fit_confidence import fit_confidence as run_fit_confidence

    config_path = Path(config)
    if not config_path.exists():
        typer.echo(
            f"config not found: {config_path} -- fit-confidence writes into an existing "
            "config file; pass --config to point at one.",
            err=True,
        )
        raise typer.Exit(2)
    cfg = load_config(config_path)
    try:
        assistant = Assistant.from_config(cfg)
    except FileNotFoundError as exc:
        typer.echo(f"{exc} (run `sprout ingest` first)", err=True)
        raise typer.Exit(2) from exc
    fit = run_fit_confidence(assistant, cfg, train, config_path)
    typer.echo(
        f"Fitted midpoint={fit.midpoint} steepness={fit.steepness} "
        f"margin_bonus={fit.margin_bonus} on {fit.n_items} train items "
        f"(dataset {fit.train_dataset_hash[:12]}, retrieval {fit.retrieval_config_hash[:12]})."
    )
    typer.echo(f"Wrote confidence.fit to {config_path}.")


@app.command()
def identify(
    image: Annotated[str, typer.Argument(help="Path to a plant photo (jpg/png).")],
    question: Annotated[str | None, typer.Option("--question", "-q")] = None,
    language: Annotated[str | None, typer.Option("--language", "-l")] = None,
    config: ConfigOpt = _DEFAULT_CONFIG,
) -> None:
    """Identify a plant from a photo, then answer from the cited corpus (or fall back)."""
    from .identify import (
        PhotoCareService,
        build_identifier,
        format_candidates,
        photo_candidates_intro_for,
    )

    cfg = _load(config)
    img = Path(image)
    if not img.exists():
        typer.echo(f"image not found: {img}", err=True)
        raise typer.Exit(2)
    try:
        assistant = Assistant.from_config(cfg)
    except FileNotFoundError as exc:
        typer.echo(f"{exc}", err=True)
        raise typer.Exit(2) from exc
    service = PhotoCareService(assistant, build_identifier(cfg), cfg)
    result = service.identify_and_answer(img.read_bytes(), question=question, language=language)
    if not result.identified or result.answer is None:
        typer.echo(result.message or "Could not identify the plant from the photo.")
        # R8/E8: "show your work" — a rejected candidate (below min_confidence, or not a
        # corpus species) is more useful surfaced than silently dropped. Never presented
        # as a resolved identification: same non-fact framing as the resolved path.
        if result.identification is not None and result.identification.candidates:
            lang = assistant.resolve_language(question or "", language)
            typer.echo(f"\n{photo_candidates_intro_for(lang)}")
            for line in format_candidates(result.identification):
                typer.echo(f"  - {line}")
        raise typer.Exit(0)
    typer.echo(result.label or "")
    typer.echo("")
    _print_answer_obj(result.answer)


# EXP-09: the table is audit tooling, deliberately not a runtime Config field — the
# answer path never reads it, and keeping it off `config.py` keeps it outside the
# tuning-scope gate's tunable surface, which is accurate: it cannot tune anything.
_DEFAULT_TOXICITY_TABLE = "corpus/toxicity.yaml"

toxicity_app = typer.Typer(
    add_completion=False, help="The structured, per-row-cited toxicity table (EXP-09)."
)
app.add_typer(toxicity_app, name="toxicity")


@toxicity_app.command("coverage")
def toxicity_coverage(
    config: ConfigOpt = _DEFAULT_CONFIG,
    table: Annotated[str, typer.Option("--table")] = _DEFAULT_TOXICITY_TABLE,
) -> None:
    """Print every species x animal pair the toxicity table covers, with its citation."""
    from .toxicity import coverage_report, load_configured_toxicity_table

    rows = load_configured_toxicity_table(table)
    report = coverage_report(rows)
    for species in sorted(report):
        typer.echo(species)
        for animal in sorted(report[species]):
            row = report[species][animal]
            status = "toxic" if row.toxic else "not listed as toxic"
            synthetic = " [synthetic]" if row.synthetic else ""
            typer.echo(
                f"  {animal:<6} {status:<18} {row.severity_class:<14} "
                f"— {row.source_name} (as of {row.fetch_date}){synthetic}"
            )
    typer.echo(f"\n{len(report)} species, {sum(len(a) for a in report.values())} pairs covered.")


@toxicity_app.command("check")
def toxicity_check(
    config: ConfigOpt = _DEFAULT_CONFIG,
    table: Annotated[str, typer.Option("--table")] = _DEFAULT_TOXICITY_TABLE,
) -> None:
    """Fail if any toxicity-table row contradicts its document's prose (EXP-09 gate)."""
    from .ingest import load_corpus
    from .toxicity import check_consistency, load_configured_toxicity_table

    cfg = _load(config)
    rows = load_configured_toxicity_table(table)
    documents = load_corpus(cfg)
    problems = check_consistency(rows, documents)
    if problems:
        typer.echo("Table-vs-prose contradictions found:", err=True)
        for p in problems:
            typer.echo(f"  - {p}", err=True)
        raise typer.Exit(1)
    typer.echo(f"{len(rows)} rows checked against corpus prose: no contradictions.")


remind_app = typer.Typer(
    add_completion=False, help="Local, offline watering/fertilizing reminders."
)
app.add_typer(remind_app, name="remind")


def _reminder_store(config: ConfigOpt) -> Any:
    from .reminders import ReminderStore

    cfg = _load(config)
    return ReminderStore(cfg.reminders.path, max_reminders=cfg.reminders.max_reminders), cfg


@remind_app.command("add")
def remind_add(
    plant: Annotated[str, typer.Argument(help="Corpus species slug or a label.")],
    kind: Annotated[str, typer.Option("--kind", "-k")] = "water",
    every: Annotated[int | None, typer.Option("--every", help="Interval in days.")] = None,
    note: Annotated[str, typer.Option("--note")] = "",
    language: Annotated[str, typer.Option("--language", "-l")] = "en",
    config: ConfigOpt = _DEFAULT_CONFIG,
) -> None:
    """Create a reminder tied to a plant (stored locally, never uploaded)."""
    from .reminders import ReminderError

    store, cfg = _reminder_store(config)
    interval = every or cfg.reminders.default_intervals.get(kind, 7)
    try:
        reminder = store.add(
            plant=plant,
            kind=kind,
            interval_days=interval,
            language=language,
            note=note,
        )
    except (ReminderError, ValueError) as exc:
        typer.echo(f"{exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"Added {reminder.kind} reminder {reminder.reminder_id} for '{reminder.plant}' "
        f"every {reminder.interval_days}d (next due {reminder.next_due})."
    )


@remind_app.command("list")
def remind_list(config: ConfigOpt = _DEFAULT_CONFIG) -> None:
    """List all reminders, soonest-due first."""
    store, _ = _reminder_store(config)
    reminders = store.all_reminders()
    if not reminders:
        typer.echo("No reminders set.")
        return
    for r in reminders:
        typer.echo(
            f"  {r.reminder_id}  {r.plant:<16} {r.kind:<10} "
            f"every {r.interval_days}d  next {r.next_due}"
        )


@remind_app.command("due")
def remind_due(config: ConfigOpt = _DEFAULT_CONFIG) -> None:
    """Show reminders that are due now."""
    store, _ = _reminder_store(config)
    due = store.due()
    if not due:
        typer.echo("Nothing due.")
        return
    for r in due:
        typer.echo(f"  DUE  {r.reminder_id}  {r.plant} — {r.kind} (was due {r.next_due})")


@remind_app.command("done")
def remind_done(
    reminder_id: Annotated[str, typer.Argument()],
    config: ConfigOpt = _DEFAULT_CONFIG,
) -> None:
    """Mark a reminder done and reschedule its next due date."""
    from .reminders import ReminderError

    store, _ = _reminder_store(config)
    try:
        r = store.complete(reminder_id)
    except ReminderError as exc:
        typer.echo(f"{exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Done. Next {r.kind} for '{r.plant}' due {r.next_due}.")


@remind_app.command("remove")
def remind_remove(
    reminder_id: Annotated[str, typer.Argument()],
    config: ConfigOpt = _DEFAULT_CONFIG,
) -> None:
    """Remove a reminder."""
    store, _ = _reminder_store(config)
    if store.remove(reminder_id):
        typer.echo(f"Removed {reminder_id}.")
    else:
        typer.echo(f"No reminder with id {reminder_id}.", err=True)
        raise typer.Exit(1)


@remind_app.command("export")
def remind_export(
    ics: Annotated[
        bool, typer.Option("--ics", help="Emit an RFC 5545 iCalendar (.ics) file.")
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write to this file instead of stdout."),
    ] = None,
    config: ConfigOpt = _DEFAULT_CONFIG,
) -> None:
    """Export reminders as a standards-based calendar file for any calendar app.

    One-directional and read-only: nothing is imported back, no sync/push channel is
    added, and the reminders JSON store stays the single source of truth (ADR-0011).
    """
    if not ics:
        typer.echo("Nothing to export: pass --ics.", err=True)
        raise typer.Exit(1)
    from .ics import reminders_to_ics

    store, _ = _reminder_store(config)
    reminders = store.all_reminders()
    text = reminders_to_ics(reminders)
    if out is not None:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"Wrote {len(reminders)} reminder(s) to {out}.")
    else:
        typer.echo(text, nl=False)


review_app = typer.Typer(
    add_completion=False,
    help=(
        "Local, opt-in review console for flagged/refused traces (EXP-17). Off by "
        "default -- see docs/RESPONSIBLE-TECH-AUDITS.md §C before enabling "
        "`review.enabled` in config."
    ),
)
app.add_typer(review_app, name="review")

_EXPORT_TARGETS = ("judge-probes", "confidence-fit", "eval-drafts")


def _review_queue(config: ConfigOpt) -> Any:
    from .review import ReviewQueue

    cfg = _load(config)
    return ReviewQueue(cfg.review.path, max_items=cfg.review.max_items)


def _print_review_item(item: Any) -> None:
    typer.echo(
        f"\n[{item.item_id}] reason={item.reason} confidence={item.confidence:.2f} "
        f"language={item.language}"
    )
    typer.echo(f"  Q: {item.question}")
    typer.echo(f"  A: {item.answer_text or '(refused, no answer text)'}")
    if item.citations:
        typer.echo("  Sources:")
        for c in item.citations:
            typer.echo(f"    - {c.label}: {c.quote}")


@review_app.command("queue")
def review_queue_cmd(
    config: ConfigOpt = _DEFAULT_CONFIG,
    show_all: Annotated[bool, typer.Option("--all", help="Include already-labeled items.")] = False,
) -> None:
    """List queued review items (unlabeled by default)."""
    queue = _review_queue(config)
    items = queue.all_items() if show_all else queue.unlabeled()
    if not items:
        typer.echo("Nothing queued." if show_all else "No unlabeled items.")
        return
    for item in items:
        status = f"labeled={item.label}" if item.label else "unlabeled"
        typer.echo(
            f"  {item.item_id}  {item.reason:<14}  conf={item.confidence:.2f}  "
            f"{status:<24}  {item.question[:60]}"
        )


@review_app.command("show")
def review_show(
    item_id: Annotated[str, typer.Argument()],
    config: ConfigOpt = _DEFAULT_CONFIG,
) -> None:
    """Print one queued item's full trace summary."""
    from .review import ReviewError

    queue = _review_queue(config)
    try:
        item = queue.get(item_id)
    except ReviewError as exc:
        typer.echo(f"{exc}", err=True)
        raise typer.Exit(1) from exc
    _print_review_item(item)


@review_app.command("label")
def review_label(
    item_id: Annotated[str, typer.Argument()],
    label: Annotated[
        str, typer.Argument(help="correct | incomplete | wrong-plant | should-have-refused")
    ],
    note: Annotated[str, typer.Option("--note")] = "",
    config: ConfigOpt = _DEFAULT_CONFIG,
) -> None:
    """Label a queued item."""
    from .review import ReviewError

    queue = _review_queue(config)
    try:
        updated = queue.label(item_id, label, note=note)
    except ReviewError as exc:
        typer.echo(f"{exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Labeled {updated.item_id} as {updated.label}.")


@review_app.command("run")
def review_run(config: ConfigOpt = _DEFAULT_CONFIG) -> None:
    """Interactive console: walk unlabeled items one at a time and prompt for a label."""
    from .review import LABELS, ReviewError

    queue = _review_queue(config)
    pending = queue.unlabeled()
    if not pending:
        typer.echo("No unlabeled items.")
        return
    typer.echo(
        f"{len(pending)} unlabeled item(s). Labels: {', '.join(LABELS)}. "
        "Enter 's' to skip, 'q' to quit."
    )
    for item in pending:
        _print_review_item(item)
        choice = typer.prompt("  Label", default="s")
        if choice == "q":
            break
        if choice in ("s", ""):
            continue
        try:
            queue.label(item.item_id, choice)
            typer.echo(f"  -> labeled {choice}")
        except ReviewError as exc:
            typer.echo(f"  {exc}", err=True)


@review_app.callback(invoke_without_command=True)
def review_default(ctx: typer.Context, config: ConfigOpt = _DEFAULT_CONFIG) -> None:
    """Bare `sprout review` launches the interactive console."""
    if ctx.invoked_subcommand is None:
        review_run(config)


@review_app.command("export")
def review_export(
    target: Annotated[str, typer.Argument(help=f"one of: {', '.join(_EXPORT_TARGETS)}")],
    out: Annotated[str | None, typer.Option("--out", help="Defaults under var/review/.")] = None,
    config: ConfigOpt = _DEFAULT_CONFIG,
) -> None:
    """Export labeled items into the judge probes / confidence-fit / eval-draft shapes.

    Always writes a standalone file for a maintainer to review and hand-merge into the
    committed, authoritative file (``eval/judge_probes.yaml`` / ``eval/suites/*.yaml``) --
    this never mutates those files itself, so nothing here silently backs a gate.
    """
    from .review import (
        export_confidence_fit_cases,
        export_eval_case_drafts,
        export_judge_probes,
        write_yaml,
    )

    if target not in _EXPORT_TARGETS:
        typer.echo(f"unknown export target {target!r}; choose from {_EXPORT_TARGETS}", err=True)
        raise typer.Exit(2)
    queue = _review_queue(config)
    items = queue.labeled()
    if not items:
        typer.echo("No labeled items to export yet -- run `sprout review label` first.", err=True)
        raise typer.Exit(1)
    exporters = {
        "judge-probes": ("var/review/export-judge-probes.yaml", export_judge_probes),
        "confidence-fit": ("var/review/export-confidence-fit.yaml", export_confidence_fit_cases),
        "eval-drafts": ("var/review/export-eval-drafts.yaml", export_eval_case_drafts),
    }
    default_out, exporter = exporters[target]
    out_path = out or default_out
    n = write_yaml(exporter(items), out_path)
    typer.echo(f"Wrote {n} {target} record(s) to {out_path}. Review before merging.")


propose_app = typer.Typer(
    add_completion=False,
    help=(
        "The SME corpus-contribution path (E5): propose a cited passage + an eval case, "
        "and review it offline against provenance, corpus-lint, safety, and "
        "representational-harm rules."
    ),
)
app.add_typer(propose_app, name="propose")


@propose_app.command("template")
def propose_template() -> None:
    """Print a fill-in-the-blanks proposal file (`sprout propose template > my-plant.yaml`)."""
    from .propose import TEMPLATE

    typer.echo(TEMPLATE, nl=False)


@propose_app.command("check")
def propose_check(
    targets: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Proposal YAML files and/or directories. Omit to review every proposal "
                "committed anywhere under --repo-root (what `make propose-check` and CI run)."
            )
        ),
    ] = None,
    config: ConfigOpt = _DEFAULT_CONFIG,
    repo_root: Annotated[
        str,
        typer.Option(
            "--repo-root",
            help="Repository root to discover proposals under and resolve sign-off artifacts in.",
        ),
    ] = ".",
    out: Annotated[
        str | None,
        typer.Option("--out", help="Directory to write corpus-proposal-review.{md,json} into."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print JSON instead of Markdown.")
    ] = False,
    today: Annotated[
        str | None,
        typer.Option("--today", help="ISO date to evaluate freshness against (default: today)."),
    ] = None,
    require_expert_review: Annotated[
        bool,
        typer.Option(
            "--require-expert-review",
            help="Also fail when a mechanically clean proposal still needs an expert sign-off.",
        ),
    ] = False,
) -> None:
    """Review corpus proposals offline: provenance, corpus lint, safety, harm checklist.

    With no ``targets`` this is the merge-blocking gate: it discovers every proposal
    committed anywhere under ``--repo-root`` — not just the worked example — and requires
    each to sit in one of the declared submission locations. Discovering none is a hard
    failure, because a gate that reviews nothing is not a gate. Naming files explicitly
    reviews exactly those and does not police where they live.

    Exits non-zero when any proposal has an error finding (``changes-requested``). A
    mechanically clean but safety-bearing proposal is reported as
    ``ready-for-expert-review`` and exits 0 unless ``--require-expert-review`` is passed
    — the tool cannot stand in for the veterinary-toxicologist / native-Spanish review
    the research roadmap requires, and it does not pretend to.
    """
    from datetime import date as _date

    from .propose import (
        PROPOSAL_DIRS,
        ProposalError,
        discover_proposals,
        proposal_paths,
        render_json,
        render_markdown,
        review_files,
    )

    cfg = _load(config)
    root = Path(repo_root)
    try:
        discovering = not targets
        if discovering:
            paths = discover_proposals(root)
            if not paths:
                raise ProposalError(
                    f"no corpus proposals found anywhere under '{root}' — expected at least "
                    f"the committed example in {list(PROPOSAL_DIRS)}. Refusing to report a "
                    "green gate over nothing."
                )
        else:
            paths = proposal_paths(targets or [])
        reviews = review_files(
            paths,
            cfg,
            today=_date.fromisoformat(today) if today else _date.today(),
            repo_root=root,
            enforce_location=discovering,
        )
    except ProposalError as exc:
        typer.echo(f"propose: {exc}", err=True)
        raise typer.Exit(2) from exc

    typer.echo(render_json(reviews) if as_json else render_markdown(reviews))
    if out is not None:
        out_dir = Path(out)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "corpus-proposal-review.md").write_text(render_markdown(reviews), "utf-8")
        (out_dir / "corpus-proposal-review.json").write_text(render_json(reviews), "utf-8")

    blocked = [r for r in reviews if r.errors]
    pending = [r for r in reviews if r.status == "ready-for-expert-review"]
    typer.echo(
        f"propose: {len(reviews)} proposal(s) — {len(blocked)} need changes, "
        f"{len(pending)} awaiting expert review."
    )
    raise typer.Exit(1 if blocked or (require_expert_review and pending) else 0)


@app.command()
def demo(config: ConfigOpt = _DEFAULT_CONFIG) -> None:
    """Reproduce a short scripted session (the `make demo` target)."""
    cfg = _load(config)
    assistant = Assistant.from_config(cfg)
    for question in (
        "Why are my Monstera's leaves yellowing?",
        "Is pothos toxic to my cat?",
        "How do I fix a flat bicycle tire?",
        "¿Con qué frecuencia riego mi Monstera en invierno?",
    ):
        typer.echo(f"\n> {question}")
        _print_answer(assistant, question, None, debug=False)


if __name__ == "__main__":  # pragma: no cover
    app()
