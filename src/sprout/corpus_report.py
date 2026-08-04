"""Corpus workbench: maintainer tooling for safe growth of the corpus (EXP-12).

``sprout corpus-report`` builds three things from the manifest + processed corpus, so
volume can grow 10x without silently degrading quality:

1. A **species x topic x language completeness matrix** against a target topic taxonomy
   (the union of ``## `` section headings used across the English documents — the
   assumed-canonical language). A species/language missing a target topic is a gap a
   contributor needs to fill.
2. An **EN/ES structural parity diff** per species: a mismatched section count between
   the mirrored files, or a Spanish heading that is byte-identical to its English
   counterpart (very likely left untranslated).
3. A **chunk-quality lint**: chunks that exceed ``chunk.max_words`` (the chunker packs
   whole sentences, so a single over-long sentence is the only way this happens), and a
   "names its plant" heuristic — the extraction-safety property visible in the current
   corpus (nearly every sentence names the plant it is about, which is what makes
   verbatim extraction unambiguous once chunks from different species sit side by side
   in a retrieval result) is currently an unwritten convention; this makes it measurable.

Findings are **advisory** (REVIEW) by default — ``sprout corpus-report`` always exits 0
unless ``--gate`` is passed — per the EXP-12 excellence bar: promote to an AUTO merge gate
once the heuristics are tuned against real contributor PRs, not on day one.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .chunk import slugify
from .config import Config
from .ingest import build_chunks, load_corpus
from .models import Document
from .text import split_sentences, strip_accents

# Advisory threshold for the "names its plant" heuristic: below this fraction of
# sentences mentioning the plant, a document is flagged (not failed).
_PLANT_NAME_THRESHOLD = 0.90

_EN_TITLE_SUFFIX_RE = re.compile(r"\s+care(?:\s+and\s+toxicity)?$", re.IGNORECASE)
_ES_TITLE_PREFIX_RE = re.compile(
    r"^cuidado(?:\s+y\s+toxicidad)?\s+de(?:l|\s+la|\s+los|\s+las)?\s+", re.IGNORECASE
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CompletenessRow(_Frozen):
    """One (species, language) row of the completeness matrix."""

    species: str
    language: str
    present_topics: tuple[str, ...]
    missing_topics: tuple[str, ...]
    extra_topics: tuple[str, ...]  # present but outside the target taxonomy

    @property
    def complete(self) -> bool:
        return not self.missing_topics


class ParityIssue(_Frozen):
    """A structural EN/ES mismatch for one species."""

    species: str
    kind: str  # missing-document | section-count-mismatch | untranslated-heading
    detail: str


class LintIssue(_Frozen):
    """A chunk-quality lint finding."""

    species: str
    file: str
    kind: str  # over-length-chunk | low-plant-name-coverage
    detail: str


class CorpusReport(_Frozen):
    """The full corpus-workbench report: a pure function of the corpus on disk."""

    target_topics: tuple[str, ...]
    species_count: int
    document_count: int
    completeness: tuple[CompletenessRow, ...]
    parity_issues: tuple[ParityIssue, ...]
    lint_issues: tuple[LintIssue, ...]

    @property
    def clean(self) -> bool:
        """True if nothing in the report needs maintainer attention."""
        return (
            not self.parity_issues
            and not self.lint_issues
            and all(row.complete for row in self.completeness)
        )


def _species_of(source: str) -> str:
    """The species slug for a corpus-relative path, e.g. ``aloe.es.md`` -> ``aloe``."""
    name = Path(source).name
    if name.endswith(".es.md"):
        return name[: -len(".es.md")]
    if name.endswith(".md"):
        return name[: -len(".md")]
    return name


def _heading_lines(text: str) -> list[str]:
    """The raw (unslugified) ``## `` section headings, in document order."""
    return [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]


def _body_sentences(text: str) -> list[str]:
    """Sentences of a processed doc's body, with ``#``/``##`` heading lines dropped."""
    body = " ".join(line for line in text.splitlines() if not line.startswith("#"))
    return split_sentences(body)


def _plant_name(title: str, language: str) -> str:
    """Strip the boilerplate "<name> care" / "Cuidado de(l/la) <name>" wrapper off a title."""
    if language == "es":
        return _ES_TITLE_PREFIX_RE.sub("", title).strip()
    return _EN_TITLE_SUFFIX_RE.sub("", title).strip()


def _name_stems(name: str) -> list[str]:
    """Fold-cased, truncated word stems used to test "does this sentence name the plant".

    Short all-caps words (e.g. "ZZ") are kept whole; other words need 4+ letters and are
    truncated to 5 chars, so mild inflection ("Dracaena" vs "Drácena") still matches.
    """
    stems: list[str] = []
    for word in re.findall(r"[A-Za-zÀ-ÿ]+", name):
        if word.isupper() and len(word) >= 2:
            stems.append(strip_accents(word).lower())
        elif len(word) >= 4:
            stems.append(strip_accents(word).lower()[:5])
    return stems


def _plant_name_coverage(doc: Document) -> tuple[int, int]:
    """(sentences naming the plant, total sentences); (0, 0) if there is nothing to check."""
    stems = _name_stems(_plant_name(doc.title, doc.language))
    if not stems:
        return (0, 0)
    sentences = _body_sentences(doc.text)
    if not sentences:
        return (0, 0)
    covered = 0
    for sentence in sentences:
        folded = strip_accents(sentence).lower()
        if any(stem in folded for stem in stems):
            covered += 1
    return covered, len(sentences)


def _canonical_topic_order(documents: list[Document]) -> tuple[str, ...]:
    """The target topic taxonomy: the most common ordered section-slug tuple in English.

    English is the assumed-canonical language for the taxonomy's shape (name and order of
    topics); which language a given passage happens to be translated *into* is a separate
    question, handled positionally in ``build_report`` and by the EN/ES parity diff.
    """
    orderings = [
        tuple(slugify(h) for h in _heading_lines(doc.text))
        for doc in documents
        if doc.language == "en"
    ]
    if not orderings:  # no English documents at all — fall back to every language
        orderings = [tuple(slugify(h) for h in _heading_lines(doc.text)) for doc in documents]
    if not orderings:
        return ()
    return Counter(orderings).most_common(1)[0][0]


def _completeness_row(
    species: str, language: str, doc: Document, target_topics: tuple[str, ...]
) -> tuple[CompletenessRow, ParityIssue | None]:
    """A doc's completeness row, matched *positionally* against the canonical order.

    A well-translated Spanish heading (e.g. "Riego" for "Watering") must count as
    present, not as a gap — literal-text mismatches are the parity diff's job
    (untranslated-heading), not the matrix's. Only the English row is also checked
    against the canonical order itself, since English defines that order.
    """
    doc_topics = tuple(slugify(h) for h in _heading_lines(doc.text))
    n = len(doc_topics)
    row = CompletenessRow(
        species=species,
        language=language,
        present_topics=target_topics[: min(n, len(target_topics))],
        missing_topics=target_topics[n:],
        extra_topics=doc_topics[len(target_topics) :],
    )
    issue = None
    if language == "en" and doc_topics[: len(target_topics)] != target_topics[:n]:
        issue = ParityIssue(
            species=species,
            kind="topic-order-mismatch",
            detail=(
                f"en headings {list(doc_topics)} do not match the corpus-wide "
                f"canonical order {list(target_topics)}"
            ),
        )
    return row, issue


def _mirror_parity_issues(species: str, en_doc: Document, es_doc: Document) -> list[ParityIssue]:
    """Structural EN/ES parity issues for one species that has both documents."""
    en_headings = _heading_lines(en_doc.text)
    es_headings = _heading_lines(es_doc.text)
    if len(en_headings) != len(es_headings):
        return [
            ParityIssue(
                species=species,
                kind="section-count-mismatch",
                detail=(
                    f"en has {len(en_headings)} sections {en_headings}; "
                    f"es has {len(es_headings)} {es_headings}"
                ),
            )
        ]
    issues = []
    for i, (en_h, es_h) in enumerate(zip(en_headings, es_headings, strict=True), start=1):
        if strip_accents(en_h).lower() == strip_accents(es_h).lower():
            issues.append(
                ParityIssue(
                    species=species,
                    kind="untranslated-heading",
                    detail=(
                        f"section {i} heading '{es_h}' in the .es.md file matches "
                        "the en heading verbatim (likely untranslated)"
                    ),
                )
            )
    return issues


def _chunk_lint_issues(config: Config, documents: list[Document]) -> list[LintIssue]:
    """Over-length chunks: the chunker packs whole sentences, so this means one sentence
    alone exceeded ``chunk.max_words``.
    """
    issues = []
    for chunk in build_chunks(config, documents):
        n_words = len(chunk.text.split())
        if n_words > config.chunk.max_words:
            issues.append(
                LintIssue(
                    species=_species_of(chunk.source),
                    file=chunk.source,
                    kind="over-length-chunk",
                    detail=(
                        f"chunk {chunk.chunk_id} (topic={chunk.topic}) is {n_words} words "
                        f"> max_words {config.chunk.max_words}"
                    ),
                )
            )
    return issues


def _plant_name_lint_issues(documents: list[Document]) -> list[LintIssue]:
    """The "names its plant" extraction-safety heuristic, per document."""
    issues = []
    for doc in documents:
        covered, total = _plant_name_coverage(doc)
        if total and covered / total < _PLANT_NAME_THRESHOLD:
            pct = covered / total
            issues.append(
                LintIssue(
                    species=_species_of(doc.source),
                    file=doc.source,
                    kind="low-plant-name-coverage",
                    detail=(
                        f"{covered}/{total} sentences ({pct:.0%}) name the plant "
                        f"('{_plant_name(doc.title, doc.language)}'); below "
                        f"{_PLANT_NAME_THRESHOLD:.0%} advisory threshold"
                    ),
                )
            )
    return issues


# --- public reuse surface ----------------------------------------------------------
#
# The SME contribution path (`sprout propose`, research item E5) reviews an *incoming*
# species against exactly the checks this maintainer-QA workbench (EXP-12) already runs
# over the *shipped* corpus. These thin wrappers exist so that reuse is a call, not a
# copy: one implementation of "what a corpus document must look like", two entry points.


def canonical_topic_order(documents: list[Document]) -> tuple[str, ...]:
    """The corpus-wide canonical topic taxonomy (slugs, in canonical order)."""
    return _canonical_topic_order(documents)


def heading_slugs(text: str) -> tuple[str, ...]:
    """The ``## `` section headings of a processed document, slugified, in order."""
    return tuple(slugify(h) for h in _heading_lines(text))


def species_of(source: str) -> str:
    """The species slug for a corpus-relative path (``aloe.es.md`` -> ``aloe``)."""
    return _species_of(source)


def mirror_parity_issues(
    species: str, en_doc: Document, es_doc: Document
) -> tuple[ParityIssue, ...]:
    """Structural EN/ES parity issues for one species that has both documents."""
    return tuple(_mirror_parity_issues(species, en_doc, es_doc))


def chunk_lint_issues(config: Config, documents: list[Document]) -> tuple[LintIssue, ...]:
    """Over-length-chunk findings for ``documents`` under this config's chunker settings."""
    return tuple(_chunk_lint_issues(config, documents))


def plant_name_lint_issues(documents: list[Document]) -> tuple[LintIssue, ...]:
    """Extraction-safety ("names its plant") findings, per document."""
    return tuple(_plant_name_lint_issues(documents))


def build_report(config: Config) -> CorpusReport:
    """Build the full corpus report from the corpus the given config points at."""
    documents = load_corpus(config)

    docs_by_species: dict[str, dict[str, Document]] = {}
    for doc in documents:
        docs_by_species.setdefault(_species_of(doc.source), {})[doc.language] = doc

    target_topics = _canonical_topic_order(documents)

    completeness: list[CompletenessRow] = []
    parity_issues: list[ParityIssue] = []
    for species in sorted(docs_by_species):
        langs = docs_by_species[species]
        for language in ("en", "es"):
            lang_doc = langs.get(language)
            if lang_doc is None:
                parity_issues.append(
                    ParityIssue(
                        species=species,
                        kind="missing-document",
                        detail=f"no {language} document for '{species}'",
                    )
                )
                continue
            row, issue = _completeness_row(species, language, lang_doc, target_topics)
            completeness.append(row)
            if issue is not None:
                parity_issues.append(issue)
        if "en" in langs and "es" in langs:
            parity_issues.extend(_mirror_parity_issues(species, langs["en"], langs["es"]))

    lint_issues = _chunk_lint_issues(config, documents) + _plant_name_lint_issues(documents)

    return CorpusReport(
        target_topics=tuple(target_topics),
        species_count=len(docs_by_species),
        document_count=len(documents),
        completeness=tuple(completeness),
        parity_issues=tuple(sorted(parity_issues, key=lambda p: (p.species, p.kind))),
        lint_issues=tuple(sorted(lint_issues, key=lambda x: (x.species, x.kind, x.file))),
    )


# --- rendering ---------------------------------------------------------------------

_DISCLAIMER = (
    "Advisory report (EXP-12): findings here do not fail CI yet. Promote to an AUTO-gate "
    "once the heuristics are tuned against real contributor PRs (`sprout corpus-report --gate`)."
)


def render_json(report: CorpusReport) -> str:
    return report.model_dump_json(indent=2)


def _matrix_table(report: CorpusReport, language: str) -> str:
    rows = [r for r in report.completeness if r.language == language]
    header = "| Species | " + " | ".join(report.target_topics) + " | Extra |"
    sep = "|---|" + "---|" * len(report.target_topics) + "---|"
    lines = [header, sep]
    for r in sorted(rows, key=lambda x: x.species):
        cells = ["✅" if t not in r.missing_topics else "❌" for t in report.target_topics]
        extra = ", ".join(r.extra_topics) if r.extra_topics else "—"
        lines.append(f"| {r.species} | " + " | ".join(cells) + f" | {extra} |")
    return "\n".join(lines)


def render_markdown(report: CorpusReport) -> str:
    complete_rows = sum(1 for r in report.completeness if r.complete)
    lines = [
        "# Sprout Corpus Report",
        "",
        f"> {_DISCLAIMER}",
        "",
        "| | |",
        "|---|---|",
        f"| Species | {report.species_count} |",
        f"| Documents | {report.document_count} |",
        f"| Target topics | {', '.join(report.target_topics)} |",
        f"| Complete (species, language) rows | {complete_rows}/{len(report.completeness)} |",
        f"| Parity issues | {len(report.parity_issues)} |",
        f"| Lint issues | {len(report.lint_issues)} |",
        f"| Overall | {'✅ clean' if report.clean else '⚠️ needs review'} |",
        "",
        "## Completeness matrix — English",
        "",
        _matrix_table(report, "en"),
        "",
        "## Completeness matrix — Spanish",
        "",
        _matrix_table(report, "es"),
        "",
        "## EN/ES parity diff",
        "",
    ]
    if report.parity_issues:
        lines += ["| Species | Kind | Detail |", "|---|---|---|"]
        lines += [f"| {p.species} | {p.kind} | {p.detail} |" for p in report.parity_issues]
    else:
        lines.append("No parity issues found.")
    lines += ["", "## Chunk-quality lint", ""]
    if report.lint_issues:
        lines += ["| Species | File | Kind | Detail |", "|---|---|---|---|"]
        lines += [f"| {i.species} | {i.file} | {i.kind} | {i.detail} |" for i in report.lint_issues]
    else:
        lines.append("No lint issues found.")
    lines.append("")
    return "\n".join(lines)
