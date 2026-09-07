"""Compare two corpus states and say what a change would move.

``corpus-report`` describes one corpus and ``freshness`` checks its dates. Neither
answers the question a reviewer actually has in front of a corpus pull request: *what
does this change?* A toxicity passage edited by one word is a safety change, and until
now nobody could see which of the eval cases exercise it without running the whole
harness.

``sprout corpus diff OLD NEW`` answers it. Each side is a corpus root: a directory
holding ``manifest.yaml`` and the processed documents (the layout ``corpus/`` uses and
the layout ``corpus install`` writes, so an installed bundle version is a valid side).

Four things shape what this is willing to claim.

**Impact is measured, not guessed.** Nothing here pattern-matches a species name against
a question. Both corpus states are ingested and both answer every eval case and every
smoke question through the ordinary offline pipeline, and the two rendered answers are
compared. A case is reported as touched because its answer or its citations actually
moved, not because a heuristic thought it might.

**Chunks are identified by position, not by id.** A chunk's id is a hash *of its own
text*, so an edited chunk does not keep its id: keying on the id would report every edit
as one removal and one unrelated addition. The key here is ``(document, topic, index
within topic)``, which survives an edit, and the pair of ids is reported alongside so the
change is still content-addressed. Inserting a passage does shift the index of everything
after it inside that one topic, and that shows up as a run of changed chunks. That is the
honest rendering of what happened, and it is why the document-level content hash is
reported too.

**An analysis that could not run says so.** If the eval dataset will not load, the eval
impact is reported as not analysed, with the reason. It is never reported as zero cases
affected. The same holds for the claims registry and for a missing toxicity table. A
count of zero and an analysis that did not happen are different facts, and only one of
them is reassuring.

**A removed document that a case still cites is an error.** It is the one finding here
that is not merely informational: the case will lose its grounding, and the diff exits
non-zero for it whether or not any gate flag was passed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ConfigDict

from .config import Config
from .determinism import sha256_of_obj, sha256_of_text, short
from .ingest import build_chunks, load_corpus
from .models import Answer, Chunk, Document
from .toxicity import ToxicityRow, load_toxicity_table

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance, types only
    from .answer import Assistant
    from .store import VectorStore

#: Manifest fields whose change is provenance, not prose. Reported per document.
MANIFEST_FIELDS: tuple[str, ...] = (
    "title",
    "language",
    "source_name",
    "url",
    "license",
    "fetch_date",
    "topic",
)

#: Toxicity-row fields compared for a change. ``species_slug``/``animal`` are the key.
TOXICITY_FIELDS: tuple[str, ...] = (
    "species_name",
    "toxic",
    "principle",
    "severity_class",
    "source_name",
    "url",
    "license",
    "fetch_date",
    "synthetic",
)

#: The prefix a ``docs/claims.yaml`` entry would use to resolve a value from the corpus.
#: No entry uses it today, which is itself worth saying out loud: see
#: :class:`ClaimsImpact`.
CORPUS_CLAIM_PREFIX = "corpus:"


class CorpusDiffError(ValueError):
    """A side of the diff could not be read. Fails closed, naming the path."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- state


class CorpusState(_Frozen):
    """One side of the comparison, ingested.

    ``fingerprint`` is a content hash over every document's provenance and text plus
    every toxicity row. Two corpus roots with the same fingerprint produce an empty diff,
    and the value is stable across runs and machines, so it can be recorded beside a
    result as the corpus that produced it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    root: str
    documents: dict[str, Document]
    chunks: dict[str, Chunk]  # "source\ttopic\tindex" -> chunk
    toxicity: tuple[ToxicityRow, ...] | None
    toxicity_missing_reason: str
    fingerprint: str


def chunk_key(source: str, topic: str, index: int) -> str:
    """The position key a chunk keeps across an edit to its own text."""
    return f"{source}\t{topic}\t{index}"


def _chunks_by_position(chunks: list[Chunk]) -> dict[str, Chunk]:
    """Re-derive each chunk's index within its (document, topic), in emission order."""
    seen: dict[tuple[str, str], int] = {}
    out: dict[str, Chunk] = {}
    for chunk in chunks:
        pair = (chunk.source, chunk.topic)
        index = seen.get(pair, 0)
        seen[pair] = index + 1
        out[chunk_key(chunk.source, chunk.topic, index)] = chunk
    return out


def _fingerprint(documents: dict[str, Document], toxicity: tuple[ToxicityRow, ...] | None) -> str:
    payload = {
        "documents": [
            {
                "source": source,
                **{field: getattr(doc, field) for field in MANIFEST_FIELDS},
                "text_sha256": sha256_of_text(doc.text),
            }
            for source, doc in sorted(documents.items())
        ],
        "toxicity": (
            None
            if toxicity is None
            else [
                row.model_dump()
                for row in sorted(toxicity, key=lambda r: (r.species_slug, r.animal))
            ]
        ),
    }
    return f"sha256:{short(sha256_of_obj(payload))}"


def config_for_root(config: Config, root: Path) -> Config:
    """``config`` with its corpus paths pointed at ``root``.

    The chunker's settings come from the caller's config, deliberately: both sides must
    be chunked the same way or the chunk diff would report the settings rather than the
    corpus.
    """
    corpus = config.corpus.model_copy(
        update={
            "path": str(root / "processed"),
            "manifest": str(root / "manifest.yaml"),
        }
    )
    return config.model_copy(update={"corpus": corpus})


def load_state(config: Config, root: str | Path) -> CorpusState:
    """Ingest one corpus root.

    The existence checks here are not decoration. ``resources.locate`` falls back to the
    corpus bundled inside the installed package when a configured path is absent, which
    is right for ``sprout ask`` on a fresh install and would be silently wrong here: a
    mistyped path would diff the packaged corpus against itself and report "no changes".
    """
    path = Path(root)
    if not path.is_dir():
        raise CorpusDiffError(f"corpus root not found: {path}")
    manifest = path / "manifest.yaml"
    processed = path / "processed"
    if not manifest.is_file():
        raise CorpusDiffError(f"{path}: no manifest.yaml (a corpus root must carry one)")
    if not processed.is_dir():
        raise CorpusDiffError(f"{path}: no processed/ directory")

    scoped = config_for_root(config, path)
    documents = {doc.source: doc for doc in load_corpus(scoped)}
    chunks = _chunks_by_position(build_chunks(scoped, list(documents.values())))

    table = path / "toxicity.yaml"
    toxicity: tuple[ToxicityRow, ...] | None = None
    reason = ""
    if table.is_file():
        toxicity = tuple(load_toxicity_table(table))
    else:
        reason = f"{table} is not a file, so no toxicity row could be compared"

    return CorpusState(
        root=str(path),
        documents=documents,
        chunks=chunks,
        toxicity=toxicity,
        toxicity_missing_reason=reason,
        fingerprint=_fingerprint(documents, toxicity),
    )


# --------------------------------------------------------------------------- rows


class FieldChange(_Frozen):
    """One field that moved, with both values."""

    field: str
    before: str
    after: str


class DocumentChange(_Frozen):
    """One document added, removed, or changed."""

    source: str
    kind: str  # added | removed | changed
    text_sha256_before: str = ""
    text_sha256_after: str = ""
    manifest_changes: tuple[FieldChange, ...] = ()

    @property
    def text_changed(self) -> bool:
        return self.kind == "changed" and self.text_sha256_before != self.text_sha256_after


class ChunkChange(_Frozen):
    """One chunk added, removed, or changed, keyed by its position."""

    source: str
    topic: str
    index: int
    kind: str  # added | removed | changed
    chunk_id_before: str = ""
    chunk_id_after: str = ""
    text_before: str = ""
    text_after: str = ""


class ToxicityChange(_Frozen):
    """One species x animal row added, removed, or changed."""

    species_slug: str
    animal: str
    kind: str  # added | removed | changed
    field_changes: tuple[FieldChange, ...] = ()


class CaseImpact(_Frozen):
    """One eval case whose rendered answer moved, measured by re-running it."""

    case_id: str
    question: str
    language: str
    kind: str  # refusal_changed | citations_changed | text_changed | grounding_lost
    cited_before: tuple[str, ...]
    cited_after: tuple[str, ...]
    detail: str


class SmokeImpact(_Frozen):
    """One corpus-derived smoke question whose answer moved, or which appeared/vanished."""

    case_id: str
    question: str
    kind: str  # added | removed | answer_changed
    detail: str


class ClaimsImpact(_Frozen):
    """What the claims registry says that this corpus change could move.

    ``analysed`` is false when the registry could not be read. When it is true and
    ``corpus_derived`` is empty, that is a real finding rather than an empty result: no
    entry in ``docs/claims.yaml`` resolves a value from the corpus, so no committed claim
    can be shown to move by a corpus edit. Making one possible means a ``corpus:`` source
    kind in ``claims.py``; until then this section reports the absence rather than
    printing a reassuring zero.
    """

    analysed: bool
    not_analysed_reason: str = ""
    corpus_derived: tuple[str, ...] = ()
    entries_read: int = 0


class ImpactSection(_Frozen):
    """The eval or smoke impact, plus whether it could be computed at all."""

    analysed: bool
    not_analysed_reason: str = ""
    cases_considered: int = 0


# --------------------------------------------------------------------------- diff


class CorpusDiff(_Frozen):
    """The whole comparison. Deterministic: no clock, every list sorted."""

    before_root: str
    after_root: str
    before_fingerprint: str
    after_fingerprint: str

    documents: tuple[DocumentChange, ...]
    chunks: tuple[ChunkChange, ...]
    toxicity: tuple[ToxicityChange, ...]
    toxicity_analysed: bool
    toxicity_not_analysed_reason: str = ""

    eval_section: ImpactSection = ImpactSection(analysed=False, not_analysed_reason="not run")
    eval_cases: tuple[CaseImpact, ...] = ()
    smoke_section: ImpactSection = ImpactSection(analysed=False, not_analysed_reason="not run")
    smoke_cases: tuple[SmokeImpact, ...] = ()
    claims: ClaimsImpact = ClaimsImpact(analysed=False, not_analysed_reason="not run")

    errors: tuple[str, ...] = ()

    @property
    def identical(self) -> bool:
        return self.before_fingerprint == self.after_fingerprint

    @property
    def empty(self) -> bool:
        """No document, chunk or toxicity row moved."""
        return not (self.documents or self.chunks or self.toxicity)

    @property
    def toxicity_changed(self) -> bool:
        return bool(self.toxicity)

    @property
    def removed_documents(self) -> tuple[str, ...]:
        return tuple(change.source for change in self.documents if change.kind == "removed")


def _document_changes(before: CorpusState, after: CorpusState) -> tuple[DocumentChange, ...]:
    changes: list[DocumentChange] = []
    for source in sorted(set(before.documents) - set(after.documents)):
        changes.append(
            DocumentChange(
                source=source,
                kind="removed",
                text_sha256_before=short(sha256_of_text(before.documents[source].text)),
            )
        )
    for source in sorted(set(after.documents) - set(before.documents)):
        changes.append(
            DocumentChange(
                source=source,
                kind="added",
                text_sha256_after=short(sha256_of_text(after.documents[source].text)),
            )
        )
    for source in sorted(set(before.documents) & set(after.documents)):
        old, new = before.documents[source], after.documents[source]
        old_hash, new_hash = short(sha256_of_text(old.text)), short(sha256_of_text(new.text))
        fields = tuple(
            FieldChange(
                field=field,
                before=str(getattr(old, field)),
                after=str(getattr(new, field)),
            )
            for field in MANIFEST_FIELDS
            if getattr(old, field) != getattr(new, field)
        )
        if old_hash == new_hash and not fields:
            continue
        changes.append(
            DocumentChange(
                source=source,
                kind="changed",
                text_sha256_before=old_hash,
                text_sha256_after=new_hash,
                manifest_changes=fields,
            )
        )
    return tuple(changes)


def _split_key(key: str) -> tuple[str, str, int]:
    source, topic, index = key.split("\t")
    return source, topic, int(index)


def _chunk_changes(before: CorpusState, after: CorpusState) -> tuple[ChunkChange, ...]:
    changes: list[ChunkChange] = []
    for key in sorted(set(before.chunks) | set(after.chunks)):
        source, topic, index = _split_key(key)
        old = before.chunks.get(key)
        new = after.chunks.get(key)
        if old is None and new is not None:
            changes.append(
                ChunkChange(
                    source=source,
                    topic=topic,
                    index=index,
                    kind="added",
                    chunk_id_after=new.chunk_id,
                    text_after=new.text,
                )
            )
        elif old is not None and new is None:
            changes.append(
                ChunkChange(
                    source=source,
                    topic=topic,
                    index=index,
                    kind="removed",
                    chunk_id_before=old.chunk_id,
                    text_before=old.text,
                )
            )
        elif old is not None and new is not None and old.text != new.text:
            changes.append(
                ChunkChange(
                    source=source,
                    topic=topic,
                    index=index,
                    kind="changed",
                    chunk_id_before=old.chunk_id,
                    chunk_id_after=new.chunk_id,
                    text_before=old.text,
                    text_after=new.text,
                )
            )
    return tuple(changes)


def _toxicity_changes(
    before: CorpusState, after: CorpusState
) -> tuple[tuple[ToxicityChange, ...], bool, str]:
    if before.toxicity is None or after.toxicity is None:
        reason = before.toxicity_missing_reason or after.toxicity_missing_reason
        return (), False, reason
    old = {(row.species_slug, row.animal): row for row in before.toxicity}
    new = {(row.species_slug, row.animal): row for row in after.toxicity}
    changes: list[ToxicityChange] = []
    for key in sorted(set(old) - set(new)):
        changes.append(ToxicityChange(species_slug=key[0], animal=key[1], kind="removed"))
    for key in sorted(set(new) - set(old)):
        changes.append(ToxicityChange(species_slug=key[0], animal=key[1], kind="added"))
    for key in sorted(set(old) & set(new)):
        fields = tuple(
            FieldChange(
                field=field,
                before=str(getattr(old[key], field)),
                after=str(getattr(new[key], field)),
            )
            for field in TOXICITY_FIELDS
            if getattr(old[key], field) != getattr(new[key], field)
        )
        if fields:
            changes.append(
                ToxicityChange(
                    species_slug=key[0],
                    animal=key[1],
                    kind="changed",
                    field_changes=fields,
                )
            )
    return tuple(changes), True, ""


# --------------------------------------------------------------------------- impact


def _answer_shape(answer: Answer) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """What is compared between the two sides: refusal, citations, rendered sentences."""
    cited = tuple(sorted({sentence.citation.source for sentence in answer.sentences}))
    text = tuple(sentence.text for sentence in answer.sentences)
    return answer.refused, cited, text


def _assistant_for(config: Config, state: CorpusState) -> tuple[Assistant, VectorStore]:
    from .answer import Assistant
    from .providers import build_embedding
    from .store import VectorStore

    scoped = config_for_root(config, Path(state.root))
    embedder = build_embedding(scoped)
    store = VectorStore()
    for chunk in sorted(state.chunks.values(), key=lambda c: c.chunk_id):
        store.add(chunk, embedder.embed(chunk.text))
    store.build_bm25(k1=scoped.retrieval.bm25_k1, b=scoped.retrieval.bm25_b)
    return Assistant.from_store(scoped, store), store


def _eval_impact(
    config: Config,
    before: CorpusState,
    after: CorpusState,
    suites_dir: str | Path,
) -> tuple[ImpactSection, tuple[CaseImpact, ...], list[str]]:
    from .eval.dataset import DatasetError, load_suite_dir

    try:
        dataset = load_suite_dir(suites_dir)
    except (OSError, DatasetError, ValueError) as exc:
        return (
            ImpactSection(
                analysed=False,
                not_analysed_reason=(
                    f"the eval dataset under {suites_dir} could not be loaded ({exc}), so no "
                    f"case impact was computed. This is not the same as no case being affected."
                ),
            ),
            (),
            [],
        )

    old_assistant, _ = _assistant_for(config, before)
    new_assistant, _ = _assistant_for(config, after)
    removed = set(before.documents) - set(after.documents)

    impacts: list[CaseImpact] = []
    errors: list[str] = []
    for item in sorted(dataset.items, key=lambda entry: entry.id):
        language = item.language or config.corpus.default_language
        old_answer = old_assistant.answer(
            item.question, language, season=item.season, light=item.light
        )
        new_answer = new_assistant.answer(
            item.question, language, season=item.season, light=item.light
        )
        old_refused, old_cited, old_text = _answer_shape(old_answer)
        new_refused, new_cited, new_text = _answer_shape(new_answer)

        lost = tuple(sorted(set(old_cited) & removed))
        if lost:
            errors.append(
                f"eval case {item.id!r} cited {', '.join(lost)}, which the new corpus does "
                f"not contain"
            )
            impacts.append(
                CaseImpact(
                    case_id=item.id,
                    question=item.question,
                    language=language,
                    kind="grounding_lost",
                    cited_before=old_cited,
                    cited_after=new_cited,
                    detail=f"cited a removed document: {', '.join(lost)}",
                )
            )
            continue

        if old_refused != new_refused:
            kind, detail = "refusal_changed", (f"refused={old_refused} then refused={new_refused}")
        elif old_cited != new_cited:
            kind, detail = "citations_changed", (f"{list(old_cited)} then {list(new_cited)}")
        elif old_text != new_text:
            kind, detail = "text_changed", "same citations, different rendered sentences"
        else:
            continue
        impacts.append(
            CaseImpact(
                case_id=item.id,
                question=item.question,
                language=language,
                kind=kind,
                cited_before=old_cited,
                cited_after=new_cited,
                detail=detail,
            )
        )

    section = ImpactSection(analysed=True, cases_considered=len(dataset.items))
    return section, tuple(impacts), errors


def _smoke_impact(
    config: Config, before: CorpusState, after: CorpusState
) -> tuple[ImpactSection, tuple[SmokeImpact, ...]]:
    from .smoke import derive_smoke_cases

    old_assistant, old_store = _assistant_for(config, before)
    new_assistant, new_store = _assistant_for(config, after)
    old_cases = {case.case_id: case for case in derive_smoke_cases(old_store)}
    new_cases = {case.case_id: case for case in derive_smoke_cases(new_store)}

    impacts: list[SmokeImpact] = []
    for case_id in sorted(set(old_cases) - set(new_cases)):
        impacts.append(
            SmokeImpact(
                case_id=case_id,
                question=old_cases[case_id].question,
                kind="removed",
                detail="the species/topic pair this question was derived from is gone",
            )
        )
    for case_id in sorted(set(new_cases) - set(old_cases)):
        impacts.append(
            SmokeImpact(
                case_id=case_id,
                question=new_cases[case_id].question,
                kind="added",
                detail="a new species/topic pair produced a new question",
            )
        )
    for case_id in sorted(set(old_cases) & set(new_cases)):
        case = new_cases[case_id]
        old_shape = _answer_shape(old_assistant.answer(case.question, case.language))
        new_shape = _answer_shape(new_assistant.answer(case.question, case.language))
        if old_shape == new_shape:
            continue
        impacts.append(
            SmokeImpact(
                case_id=case_id,
                question=case.question,
                kind="answer_changed",
                detail=(
                    f"cited {list(old_shape[1])} then {list(new_shape[1])}"
                    if old_shape[1] != new_shape[1]
                    else "same citations, different rendered answer"
                ),
            )
        )
    considered = len(set(old_cases) | set(new_cases))
    return ImpactSection(analysed=True, cases_considered=considered), tuple(impacts)


def _claims_impact(claims_path: str | Path) -> ClaimsImpact:
    path = Path(claims_path)
    if not path.is_file():
        return ClaimsImpact(
            analysed=False,
            not_analysed_reason=f"{path} is not a file, so no claim could be checked",
        )
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return ClaimsImpact(analysed=False, not_analysed_reason=f"{path} is not valid YAML ({exc})")
    entries = (raw or {}).get("claims") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return ClaimsImpact(
            analysed=False,
            not_analysed_reason=f"{path} has no 'claims' list, so no claim could be checked",
        )
    derived = tuple(
        sorted(
            str(entry.get("id"))
            for entry in entries
            if isinstance(entry, dict)
            and str(entry.get("source", "")).startswith(CORPUS_CLAIM_PREFIX)
        )
    )
    return ClaimsImpact(analysed=True, corpus_derived=derived, entries_read=len(entries))


def diff_corpora(
    config: Config,
    before_root: str | Path,
    after_root: str | Path,
    *,
    suites_dir: str | Path = "eval/suites",
    claims_path: str | Path = "docs/claims.yaml",
    with_impact: bool = True,
) -> CorpusDiff:
    """Compare two corpus roots and return the whole comparison."""
    before = load_state(config, before_root)
    after = load_state(config, after_root)

    documents = _document_changes(before, after)
    chunks = _chunk_changes(before, after)
    toxicity, toxicity_analysed, toxicity_reason = _toxicity_changes(before, after)

    errors: list[str] = []
    eval_section = ImpactSection(
        analysed=False, not_analysed_reason="impact analysis was not requested"
    )
    eval_cases: tuple[CaseImpact, ...] = ()
    smoke_section = eval_section
    smoke_cases: tuple[SmokeImpact, ...] = ()
    claims = ClaimsImpact(analysed=False, not_analysed_reason="impact analysis was not requested")
    if with_impact:
        eval_section, eval_cases, eval_errors = _eval_impact(config, before, after, suites_dir)
        errors.extend(eval_errors)
        smoke_section, smoke_cases = _smoke_impact(config, before, after)
        claims = _claims_impact(claims_path)

    return CorpusDiff(
        before_root=before.root,
        after_root=after.root,
        before_fingerprint=before.fingerprint,
        after_fingerprint=after.fingerprint,
        documents=documents,
        chunks=chunks,
        toxicity=toxicity,
        toxicity_analysed=toxicity_analysed,
        toxicity_not_analysed_reason=toxicity_reason,
        eval_section=eval_section,
        eval_cases=eval_cases,
        smoke_section=smoke_section,
        smoke_cases=smoke_cases,
        claims=claims,
        errors=tuple(sorted(errors)),
    )


def exit_code_for(diff: CorpusDiff, *, fail_on_toxicity_change: bool) -> int:
    """0 unless something the caller asked to fail on happened.

    An error always fails: a case that cites a document the new corpus does not have is
    broken grounding, not a preference. The toxicity gate is opt-in, because a corpus
    pull request that edits a toxicity passage is a normal thing to open and an abnormal
    thing to merge unreviewed.
    """
    if diff.errors:
        return 1
    if fail_on_toxicity_change and diff.toxicity_changed:
        return 1
    return 0


# --------------------------------------------------------------------------- render


def render_json(diff: CorpusDiff) -> str:
    return diff.model_dump_json(indent=2) + "\n"


def _truncate(text: str, limit: int = 160) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _table(lines: list[str], header: list[str], rows: list[list[str]]) -> None:
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    lines.append("")


def _render_section(lines: list[str], section: ImpactSection, what: str) -> bool:
    """Write the not-analysed notice if there is one. True when the section ran."""
    if section.analysed:
        return True
    lines.append(f"**Not analysed.** {section.not_analysed_reason}")
    lines.append("")
    lines.append(
        f"No {what} is reported as unaffected here, because none was examined. "
        "An analysis that did not run is not a result of zero."
    )
    lines.append("")
    return False


def _render_documents(lines: list[str], diff: CorpusDiff) -> None:
    lines.append("## Documents")
    lines.append("")
    if not diff.documents:
        lines.append("No document was added, removed, or changed.")
        lines.append("")
        return
    _table(
        lines,
        ["Document", "Change", "Text (before)", "Text (after)", "Manifest"],
        [
            [
                f"`{change.source}`",
                change.kind,
                change.text_sha256_before or "n/a",
                change.text_sha256_after or "n/a",
                ", ".join(
                    f"{field.field}: {field.before!r} -> {field.after!r}"
                    for field in change.manifest_changes
                )
                or "unchanged",
            ]
            for change in diff.documents
        ],
    )


def _render_chunks(lines: list[str], diff: CorpusDiff) -> None:
    lines.append("## Chunks")
    lines.append("")
    lines.append(
        "Keyed by (document, topic, index within topic), because a chunk id is a hash of "
        "the chunk's own text and does not survive an edit. Inserting a passage shifts "
        "the index of every later chunk in that one topic."
    )
    lines.append("")
    if not diff.chunks:
        lines.append("No chunk changed.")
        lines.append("")
        return
    _table(
        lines,
        ["Document", "Topic", "#", "Change", "Chunk id", "Text"],
        [
            [
                f"`{change.source}`",
                f"`{change.topic}`",
                str(change.index),
                change.kind,
                f"{change.chunk_id_before or 'n/a'} -> {change.chunk_id_after or 'n/a'}",
                _truncate(change.text_after or change.text_before),
            ]
            for change in diff.chunks
        ],
    )


def _render_toxicity(lines: list[str], diff: CorpusDiff) -> None:
    lines.append("## Toxicity table")
    lines.append("")
    if not diff.toxicity_analysed:
        lines.append(f"**Not analysed.** {diff.toxicity_not_analysed_reason}")
        lines.append("")
        lines.append(
            "No toxicity row is reported as unchanged here. A missing table is not a "
            "table with no changes in it."
        )
        lines.append("")
        return
    if not diff.toxicity:
        lines.append("No toxicity row changed.")
        lines.append("")
        return
    _table(
        lines,
        ["Species", "Animal", "Change", "Fields"],
        [
            [
                f"`{change.species_slug}`",
                change.animal,
                change.kind,
                ", ".join(
                    f"{field.field}: {field.before!r} -> {field.after!r}"
                    for field in change.field_changes
                )
                or "n/a",
            ]
            for change in diff.toxicity
        ],
    )


def _render_eval(lines: list[str], diff: CorpusDiff) -> None:
    lines.append("## Eval cases affected")
    lines.append("")
    lines.append(
        "Measured by answering every case through the offline pipeline against both "
        "corpus states and comparing the rendered answers, not by matching names."
    )
    lines.append("")
    if not _render_section(lines, diff.eval_section, "eval case"):
        return
    if not diff.eval_cases:
        lines.append(
            f"{diff.eval_section.cases_considered} cases were re-run against both corpus "
            "states. None changed its refusal, its citations, or its rendered sentences."
        )
        lines.append("")
        return
    _table(
        lines,
        ["Case", "Language", "Change", "Cited before", "Cited after", "Detail"],
        [
            [
                f"`{impact.case_id}`",
                impact.language,
                impact.kind,
                ", ".join(impact.cited_before) or "none",
                ", ".join(impact.cited_after) or "none",
                _truncate(impact.detail),
            ]
            for impact in diff.eval_cases
        ],
    )
    lines.append(f"{len(diff.eval_cases)} of {diff.eval_section.cases_considered} cases moved.")
    lines.append("")


def _render_smoke(lines: list[str], diff: CorpusDiff) -> None:
    lines.append("## Smoke questions affected")
    lines.append("")
    if not _render_section(lines, diff.smoke_section, "smoke question"):
        return
    if not diff.smoke_cases:
        lines.append(
            f"{diff.smoke_section.cases_considered} corpus-derived questions were re-run "
            "against both corpus states. None changed."
        )
        lines.append("")
        return
    _table(
        lines,
        ["Question id", "Change", "Detail"],
        [
            [f"`{impact.case_id}`", impact.kind, _truncate(impact.detail)]
            for impact in diff.smoke_cases
        ],
    )


def _render_claims(lines: list[str], diff: CorpusDiff) -> None:
    lines.append("## Claims registry")
    lines.append("")
    if not diff.claims.analysed:
        lines.append(f"**Not analysed.** {diff.claims.not_analysed_reason}")
        lines.append("")
        return
    if diff.claims.corpus_derived:
        lines.append("These registry entries resolve a value from the corpus:")
        lines.append("")
        for claim_id in diff.claims.corpus_derived:
            lines.append(f"- `{claim_id}`")
        lines.append("")
        lines.append("Re-run `sprout claims-check` after adopting this corpus change.")
        lines.append("")
        return
    lines.append(
        f"{diff.claims.entries_read} registry entries were read and none resolves a value "
        f"from the corpus (no `{CORPUS_CLAIM_PREFIX}` source kind exists), so this diff "
        "cannot show a committed claim moving. That is a gap in the registry, not evidence "
        "that the documents are in step with the corpus."
    )
    lines.append("")


def render_markdown(diff: CorpusDiff) -> str:
    lines: list[str] = ["# Corpus diff", ""]
    lines.append(f"- Before: `{diff.before_root}` ({diff.before_fingerprint})")
    lines.append(f"- After: `{diff.after_root}` ({diff.after_fingerprint})")
    lines.append("")
    if diff.identical:
        lines.append(
            "The two corpus states have the same fingerprint: same documents, same text, "
            "same provenance, same toxicity rows. There is nothing to compare."
        )
        lines.append("")
        return "\n".join(lines)

    if diff.errors:
        lines.append("## Errors")
        lines.append("")
        for error in diff.errors:
            lines.append(f"- {error}")
        lines.append("")

    _render_documents(lines, diff)
    _render_chunks(lines, diff)
    _render_toxicity(lines, diff)
    _render_eval(lines, diff)
    _render_smoke(lines, diff)
    _render_claims(lines, diff)
    return "\n".join(lines)
