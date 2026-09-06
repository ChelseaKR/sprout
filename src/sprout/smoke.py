"""Phase 1 CI smoke suite: cheap, corpus-*derived* sanity checks over the whole corpus.

Unlike the hand-authored Phase 2 eval suites (curated YAML cases under ``eval/suites/``),
nobody writes a single question for this suite. Every case is derived mechanically from
whatever is actually ingested right now: one question per (species, topic) pair discovered
in the populated store, built from the corpus's own species slug (the citation source
filename) and the corpus's own topic taxonomy (the ``## <topic>`` Markdown headings chunked
in ``chunk.py``). Add a 17th species or a new topic heading to the corpus and this suite
grows on the next ingest — there is no YAML to hand-maintain, so coverage cannot silently
fall behind the corpus the way a curated case list can.

It runs the deterministic offline generator only (no LLM judge, no network), so it is fast
enough to run on every PR as a first-line canary: a species/topic combination with broken
retrieval, a citation guard regression, or a species leak across the topic filter fails
loudly in seconds — well before the heavier judged eval harness (Phase 2, ``sprout eval``)
runs its own, differently-scoped case set.

This closes the gap docs/ROADMAP.md tracked under Phase 1: "a dedicated CI smoke suite of
corpus-derived questions beyond what the eval harness (Phase 2) already exercises."
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .answer import Assistant
from .config import Config
from .guards import asserts_safety
from .models import Answer
from .retrieve import species_slug
from .store import VectorStore

# Per-topic question templates, keyed by the corpus's own topic slug (see chunk.py — a
# topic slug is ``slugify()`` of the document's "## <topic>" heading). A topic slug not
# covered here still gets a case via the generic fallback below, so a brand-new corpus
# topic can never silently escape smoke coverage.
_TOPIC_QUESTIONS: dict[str, str] = {
    "watering": "How often should I water my {species}?",
    "light": "How much light does my {species} need?",
    "toxicity": "Is my {species} toxic to my cat?",
    "soil-and-repotting": "What soil should I repot my {species} in?",
    "common-problems": "Why does my {species} look unhealthy?",
}

_FALLBACK_QUESTION = "What does the source say about {topic} for my {species}?"

# Topics whose answer must never read as a safety certification, regardless of what the
# cited source says about it (the "never-certify-safe" rule — CLAUDE.md hard rule #2).
_SAFETY_TOPICS = frozenset({"toxicity"})


@dataclass(frozen=True)
class SmokeCase:
    """One corpus-derived smoke question and the species/topic it was derived from."""

    species: str
    topic: str
    question: str
    language: str = "en"

    @property
    def case_id(self) -> str:
        return f"{self.species}:{self.topic}:{self.language}"


@dataclass(frozen=True)
class SmokeCaseResult:
    case: SmokeCase
    reasons: tuple[str, ...] = field(default_factory=tuple)
    answer: Answer | None = None

    @property
    def passed(self) -> bool:
        return not self.reasons


@dataclass(frozen=True)
class SmokeResult:
    cases: tuple[SmokeCaseResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.cases) and all(c.passed for c in self.cases)

    @property
    def failures(self) -> tuple[SmokeCaseResult, ...]:
        return tuple(c for c in self.cases if not c.passed)


def derive_smoke_cases(store: VectorStore, *, language: str = "en") -> list[SmokeCase]:
    """Build one case per (species, topic) pair actually present in ``store``.

    Restricted to ``language`` (English by default): the question templates above are
    English-only by design — Spanish coverage of the same corpus is the multilingual eval
    suite's job (Phase 2's ``eval/suites/multilingual.yaml``), not this smoke net's. Cases
    are sorted for a stable, reviewable, deterministic ordering.
    """
    pairs: set[tuple[str, str]] = set()
    for chunk in store.all_chunks():
        if chunk.language != language:
            continue
        pairs.add((species_slug(chunk.source), chunk.topic))

    cases: list[SmokeCase] = []
    for species, topic in sorted(pairs):
        display = species.replace("-", " ")
        template = _TOPIC_QUESTIONS.get(topic, _FALLBACK_QUESTION)
        question = template.format(species=display, topic=topic.replace("-", " "))
        cases.append(SmokeCase(species=species, topic=topic, question=question, language=language))
    return cases


def _reasons_for(cfg: Config, case: SmokeCase, answer: Answer) -> tuple[str, ...]:
    """Pure check of one rendered ``answer`` against its case's expectations.

    Split out from :func:`_check_case` so the never-certify-safe double-check below is
    directly testable against a hand-built ``Answer`` — that invariant is *also* enforced
    structurally by ``guards.safety_filter`` inside ``Assistant.answer``, so no answer the
    live pipeline renders should ever trip it; this is defense-in-depth for a regression
    in that upstream guard, not the primary path.
    """
    reasons: list[str] = []

    if answer.refused:
        reasons.append(f"refused ({answer.refusal_reason}) for an in-corpus question")
    if not answer.citations:
        reasons.append("no citation in the rendered answer")
    else:
        cited_species = {species_slug(c.source) for c in answer.citations}
        if case.species not in cited_species:
            reasons.append(
                f"grounded in {sorted(cited_species)} instead of {case.species!r} "
                "(species leak across the topic filter)"
            )
    if case.topic in _SAFETY_TOPICS:
        for sentence in answer.sentences:
            if asserts_safety(sentence.text, case.language, cfg.guards):
                reasons.append(f"safety-topic sentence reads as a certification: {sentence.text!r}")

    return tuple(reasons)


def _check_case(assistant: Assistant, cfg: Config, case: SmokeCase) -> SmokeCaseResult:
    answer = assistant.answer(case.question, case.language)
    return SmokeCaseResult(case=case, reasons=_reasons_for(cfg, case, answer), answer=answer)


def run_smoke(
    assistant: Assistant, store: VectorStore, cfg: Config, *, language: str = "en"
) -> SmokeResult:
    """Run every corpus-derived case through the live ``assistant``."""
    cases = derive_smoke_cases(store, language=language)
    return SmokeResult(cases=tuple(_check_case(assistant, cfg, c) for c in cases))


def to_markdown(result: SmokeResult) -> str:
    """A short, human-readable summary — enough to see what failed and why."""
    lines = [
        "# Sprout smoke suite (Phase 1 — corpus-derived questions)",
        "",
        f"{len(result.cases)} cases, {len(result.failures)} failed.",
        "",
    ]
    if result.failures:
        lines.append("## Failures")
        lines.append("")
        for r in result.failures:
            lines.append(f"- `{r.case.case_id}` — {r.case.question!r}")
            for reason in r.reasons:
                lines.append(f"    - {reason}")
        lines.append("")
    lines.append("## All cases")
    lines.append("")
    lines.append("| case | question | status |")
    lines.append("|---|---|---|")
    for r in result.cases:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"| `{r.case.case_id}` | {r.case.question} | {status} |")
    return "\n".join(lines) + "\n"
