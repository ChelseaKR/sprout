"""The ``sprout`` command-line interface.

Subcommands: ``ingest`` (build the index), ``ask`` (a cited answer or honest refusal),
``serve`` (the chat UI + API), ``eval`` (record the live engine, run the suites, regenerate
the committed report), ``a11y-check`` (structural WCAG gate on rendered HTML), ``calibrate``
(judge agreement + kappa), and ``demo`` (a scripted session). Everything runs offline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml

from . import __version__
from .a11y import check_html
from .answer import Assistant
from .config import Config, load_config

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


def _print_answer(assistant: Assistant, question: str, language: str | None, debug: bool) -> None:
    answer = assistant.answer(question, language)
    typer.echo(answer.display_text)
    if answer.citations:
        typer.echo("\nSources:")
        for c in answer.citations:
            typer.echo(f"  - {c.label}")
    if answer.as_of:
        typer.echo(f"\nBased on references as of {answer.as_of}.")
    flag = " (low confidence)" if answer.low_confidence and not answer.refused else ""
    typer.echo(f"[confidence {answer.confidence:.2f}{flag} · {answer.disclosure}]")
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
    """Record the live engine over the cases, run the suites, regenerate the report."""
    from .eval.dataset import load_suite_dir
    from .eval.judge import build_judge
    from .eval.record import record
    from .eval.report import render_markdown, write_reports
    from .eval.runner import run_evaluation
    from .eval.suite import resolve_suites

    cfg = _load(config)
    assistant = Assistant.from_config(cfg)
    dataset = load_suite_dir(suite_dir, verify_hash=not update_baseline)
    golden = record(assistant, dataset, cfg)
    result = run_evaluation(
        golden,
        build_judge(judge),
        resolve_suites(suites),
        target=_target_name(cfg),
        statistical_gate=statistical_gate,
    )
    write_reports(result, out)
    typer.echo(render_markdown(result))
    if update_baseline:
        Path(out, "eval-baseline.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
    raise typer.Exit(result.exit_code)


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


@app.command()
def calibrate(
    probes: Annotated[str, typer.Argument()] = "eval/judge_probes.yaml",
    judge: Annotated[str, typer.Option("--judge")] = "deterministic",
    out: Annotated[str, typer.Option("--out")] = "docs/audits",
    gate: Annotated[bool, typer.Option("--gate")] = False,
) -> None:
    """Calibrate the judge against human-labeled probes (agreement + Cohen's kappa).

    Reports by default (exit 0); pass ``--gate`` to fail when below threshold. The
    deterministic judge is the reproducible offline floor and is reported, not gated;
    gate the calibrated LLM judge (``--judge llm --gate``) before it backs a production run.
    """
    from .eval.calibration import JudgeProbe, to_markdown
    from .eval.calibration import calibrate as run_calibrate
    from .eval.judge import build_judge

    raw = yaml.safe_load(Path(probes).read_text(encoding="utf-8"))
    items = [JudgeProbe.model_validate(p) for p in (raw.get("probes", raw))]
    record = run_calibrate(build_judge(judge), items)
    Path(out, "judge-calibration.json").write_text(record.model_dump_json(indent=2), "utf-8")
    Path(out, "judge-calibration.md").write_text(to_markdown(record), encoding="utf-8")
    typer.echo(
        f"agreement={record.agreement:.3f} kappa={record.cohens_kappa:.3f} "
        f"meets_threshold={record.meets_threshold}"
    )
    raise typer.Exit(1 if gate and not record.meets_threshold else 0)


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
