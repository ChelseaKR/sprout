"""The ``sprout`` command-line interface.

Subcommands: ``ingest`` (build the index), ``ask`` (a cited answer or honest refusal),
``serve`` (the chat UI + API), ``eval`` (record the live engine, run the suites, regenerate
the committed report), ``a11y-check`` (structural WCAG gate on rendered HTML), ``freshness``
(offline citation-freshness check, opt-in link-liveness), ``claims-check`` (doc claims vs
their code/config source of truth), ``smoke`` (the Phase 1 CI smoke suite of corpus-derived
questions), ``check-tuning-scope`` (fail-closed gate for tunable-surface changes),
``calibrate`` (judge agreement + kappa),
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
    return f"{cfg.generation.provider}:{cfg.generation.model or 'extractive'}"


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


def _print_answer_obj(answer: Answer) -> None:
    typer.echo(answer.display_text)
    if answer.citations:
        typer.echo("\nSources:")
        for c in answer.citations:
            typer.echo(f"  - {c.label}")
    if answer.as_of:
        typer.echo(f"\nBased on references as of {answer.as_of}.")
    flag = " (low confidence)" if answer.low_confidence and not answer.refused else ""
    typer.echo(f"[confidence {answer.confidence:.2f}{flag} · {answer.disclosure}]")


def _print_answer(assistant: Assistant, question: str, language: str | None, debug: bool) -> None:
    answer = assistant.answer(question, language)
    _print_answer_obj(answer)
    if debug:
        trace = assistant.trace(question, language)
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
    _print_answer(assistant, question, language, debug)


@app.command()
def serve(
    config: ConfigOpt = _DEFAULT_CONFIG,
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
) -> None:  # pragma: no cover - launches a blocking server
    """Run the accessible chat UI and JSON/SSE API."""
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
) -> None:
    """Record the live engine over the cases, run the suites, regenerate the report.

    Unless ``--update-baseline`` is passed, the run is also diffed against the committed
    ``<out>/eval-baseline.json`` (fingerprint comparability, PASS->FAIL flips, and score
    erosion beyond tolerance); any issue — including a stale baseline whose fingerprint no
    longer matches this run's dataset/judge/target — fails the command even if every suite
    individually passed its own threshold.
    """
    from .eval.dataset import load_suite_dir, write_sidecar
    from .eval.judge import build_judge
    from .eval.record import record
    from .eval.report import diff_against_baseline, load_run_result, render_markdown, write_reports
    from .eval.runner import run_evaluation
    from .eval.suite import resolve_suites
    from .eval.suites.refusal import threshold_for as refusal_threshold_for

    cfg = _load(config)
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
    write_reports(result, out)
    typer.echo(render_markdown(result))
    exit_code = result.exit_code
    baseline_path = Path(out, "eval-baseline.json")
    if update_baseline:
        baseline_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    elif baseline_path.exists():
        baseline = load_run_result(baseline_path)
        issues = diff_against_baseline(result, baseline)
        if issues:
            typer.echo("\nBaseline regression check FAILED:", err=True)
            for issue in issues:
                typer.echo(f"  - {issue}", err=True)
            exit_code = 1
        else:
            typer.echo("\nBaseline regression check: no issues.")
    else:
        typer.echo(
            f"\nNo committed baseline at {baseline_path} — skipping regression check "
            "(run `sprout eval --update-baseline` once to create it).",
            err=True,
        )
    raise typer.Exit(exit_code)


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

    No-op when the diff does not touch the tunable surface. Otherwise every commit range must
    carry a ``Tunes-Against: <case-id>[, <case-id>...]`` trailer whose ids already appear in
    ``<baseline>``'s committed ``failing_examples``.
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


@app.command()
def identify(
    image: Annotated[str, typer.Argument(help="Path to a plant photo (jpg/png).")],
    question: Annotated[str | None, typer.Option("--question", "-q")] = None,
    language: Annotated[str | None, typer.Option("--language", "-l")] = None,
    config: ConfigOpt = _DEFAULT_CONFIG,
) -> None:
    """Identify a plant from a photo, then answer from the cited corpus (or fall back)."""
    from .identify import PhotoCareService, build_identifier

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
        raise typer.Exit(0)
    typer.echo(result.label or "")
    typer.echo("")
    _print_answer_obj(result.answer)


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
