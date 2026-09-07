"""What corpus and what configuration is the published browser bundle actually running?

``scripts/export_web_bundle.py`` writes the two static assets the TypeScript port
(``web-static/``) answers from: ``data/config.json`` (thresholds, deny-lists, prompt
strings, exported from the validated :class:`~sprout.config.Config`) and
``data/index.json`` (the built vector/BM25 index). Until now the exported config carried
one provenance field, ``format_version``, and **nothing read it** -- the index's own
``format_version`` is checked in ``store.ts``, but the config bundle's was written and
never looked at by any surface. So a deployed bundle could not be asked the only question
that matters about it:

    *Is this the corpus and the configuration this checkout describes, or an older one?*

That question is the shared prerequisite under two open pieces of work. A parity gate
between the browser port and the Python engine (#143) compares the two implementations'
answers, and that comparison means nothing if the browser was answering from last month's
index -- the mismatch would be reported as a port bug. An offline-installable reference
(#149) has to tell a reader which corpus their cached copy answers from, and has to
distinguish "a new deploy exists" from "your cache is fine", which needs an identity for
the bundle rather than a cache-busting guess.

What is recorded, and why each one
----------------------------------

``corpus_fingerprint``
    Byte-for-byte the value ``sprout corpus diff`` reports for the same corpus root: a
    content hash over every document's provenance fields and text plus every toxicity
    row. It is computed by calling :func:`sprout.corpus_diff.corpus_fingerprint`, not by
    reimplementing it, so the two can never disagree about what a corpus *is*. That is
    the whole point of reusing it: a reviewer can put a deployed bundle's fingerprint
    beside a ``corpus diff`` report and see directly whether the site is answering from
    the before-side or the after-side of a corpus change.

``config_sha256``
    A hash over the exported settings themselves -- everything except the provenance
    block, so it is not self-referential. Editing ``abstain_threshold`` in
    ``config/sprout.yaml`` and shipping without re-exporting is exactly the divergence
    issue #108 found live, and this is what makes it a failed check instead of a silent
    disagreement about when to abstain.

``index_sha256`` and ``index_chunk_ids_sha256``
    Two different questions. The first is "are these the same bytes ``make ingest``
    wrote", which catches a truncated or hand-edited copy. The second is the one that
    catches the stale bundle that would otherwise slip through: **re-exporting without
    re-ingesting** leaves a fresh ``config.json`` beside an index built from the older
    corpus, and since the exporter copies whatever ``var/index.json`` holds, a
    file-bytes check alone would compare the stale index against itself and pass. A
    chunk id is a hash of the chunk's own text, so hashing the sorted chunk ids of the
    index and comparing against the ids the *current* corpus chunks to answers "was this
    index built from this corpus" rather than "was this index copied faithfully".

``corpus_as_of_earliest`` / ``corpus_as_of_latest`` / ``corpus_dates_unmeasurable``
    Hard rule 3 is that the surface says "based on references as of <date>", and an
    offline banner needs one for the bundle as a whole. Three states, not two: a
    ``fetch_date`` that is absent, malformed, **or in the future** is unmeasurable, and
    is counted rather than folded into the range. A future date is not the freshest
    data in the corpus; it is a broken record, and letting it set ``latest`` would make
    the banner advertise a snapshot that has not happened. When nothing is measurable
    both bounds are the empty string, which the banner must render as unknown -- never
    as a date.

Fail closed, everywhere
-----------------------

:func:`check_bundle` reports a problem for a missing bundle, an unparseable one, a
``format_version`` it does not know, and a bundle with no provenance block at all. That
last one is the case this module was written against: a bundle exported before this
existed carries ``format_version: 1`` and no fingerprints, and the wrong thing to do with
it is to skip the comparison and exit zero. An unanswerable question is not a pass.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

# Read under its private name deliberately — see the note beside it in
# `confidence.py`: renaming it would change that module's AST and demand a
# `Tunes-Against:` citation from a change that tunes nothing.
from .confidence import _DEFAULT_WELL_SUPPORTED_CUTOFF
from .config import Config, load_config
from .determinism import sha256_of_bytes, sha256_of_file, sha256_of_obj
from .ingest import build_chunks, load_corpus
from .models import Document

#: Version of ``data/config.json``'s own schema.
#:
#: 1 -> 2 when the provenance block was added: a version-1 bundle carries no
#: fingerprints at all, so it cannot be checked and must not be read as agreeing.
#:
#: 2 -> 3 when the confidence band's cut point and its localized labels were added. A
#: version-2 bundle carries neither, and the browser cannot invent them: a missing
#: cutoff compares as ``confidence >= undefined``, which is false for every score, so
#: every answered question would be labelled "partially supported — verify" and a
#: well-supported answer would be understated with nothing failing. That is a missing
#: value rendered as a measurement, so a version-2 bundle is rejected rather than
#: defaulted.
BUNDLE_FORMAT_VERSION = 3

#: The two files a bundle consists of, relative to the bundle directory.
CONFIG_FILE = "config.json"
INDEX_FILE = "index.json"


class WebBundleError(ValueError):
    """A bundle could not be read or its inputs could not be resolved. Fails closed."""


class BundleProvenance(BaseModel):
    """The identity of one exported bundle: which corpus, which settings, which index."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corpus_fingerprint: str
    corpus_documents: int
    corpus_as_of_earliest: str
    corpus_as_of_latest: str
    corpus_dates_unmeasurable: int
    config_sha256: str
    index_sha256: str
    index_chunks: int
    index_chunk_ids_sha256: str

    @property
    def as_of_display(self) -> str:
        """What a banner may say about this bundle's dates, including when it may not.

        Never invents a date. With no measurable ``fetch_date`` anywhere in the corpus
        the answer is the word ``unknown``, because "as of " with nothing after it reads
        as a rendering bug and "as of today" would be a lie.
        """
        if not self.corpus_as_of_earliest or not self.corpus_as_of_latest:
            return "unknown"
        if self.corpus_as_of_earliest == self.corpus_as_of_latest:
            return self.corpus_as_of_latest
        return f"{self.corpus_as_of_earliest} to {self.corpus_as_of_latest}"


# --------------------------------------------------------------------------- settings


def settings_payload(cfg: Config) -> dict[str, Any]:
    """Everything in the bundle that the TypeScript port actually runs on.

    Kept separate from the provenance block for two reasons: the provenance hashes this
    payload and cannot hash itself, and both the exporter and the checker build the
    payload through this one function, so a field added here reaches the shipped bundle
    and the staleness check in the same edit. A second, hand-copied definition of "the
    exported settings" is how the check would come to pass over a field it no longer
    covers.
    """
    return {
        "retrieval": {
            "top_k": cfg.retrieval.top_k,
            "min_score": cfg.retrieval.min_score,
            "embedding_dim": cfg.retrieval.embedding_dim,
            "hybrid": cfg.retrieval.hybrid,
            "bm25_k1": cfg.retrieval.bm25_k1,
            "bm25_b": cfg.retrieval.bm25_b,
            "rrf_k": cfg.retrieval.rrf_k,
            "dedup_threshold": cfg.retrieval.dedup_threshold,
            "topic_filter": cfg.retrieval.topic_filter,
            "species_aliases": cfg.retrieval.species_aliases,
        },
        "generation": {
            "max_sentences": cfg.generation.max_sentences,
            "relevance_floor": cfg.generation.relevance_floor,
            "support_overlap": cfg.generation.support_overlap,
        },
        "confidence": {
            "abstain_threshold": cfg.confidence.abstain_threshold,
            "low_confidence_threshold": cfg.confidence.low_confidence_threshold,
            # The logistic's shape, when `sprout fit-confidence` (ADR-0016) has written
            # one. Python reads it in `confidence.py::_constants`; without it here the
            # browser would keep using the ADR-0012 defaults and compute a different
            # confidence — and therefore different abstain/low-confidence decisions —
            # than the CLI for the same question, silently, from the first committed
            # fit onward (issue #108). `null` when no fit is committed, which is what
            # tells the TypeScript side to use the same defaults Python would.
            "fit": (
                None
                if cfg.confidence.fit is None
                else {
                    "midpoint": cfg.confidence.fit.midpoint,
                    "steepness": cfg.confidence.fit.steepness,
                    "margin_bonus": cfg.confidence.fit.margin_bonus,
                }
            ),
            # The well-supported/partially-supported cut point (EXP-06), derived in
            # `confidence.py` from the committed reliability diagram. Exported rather
            # than mirrored in TypeScript for the same reason `fit` is: a hand-copied
            # twin is correct until the next `sprout fit-confidence`, after which the
            # browser and the CLI would put the same confidence in different bands with
            # nothing failing. Below `abstain_threshold` the band is
            # `insufficient_evidence`, so that threshold is the second cut point and is
            # already exported above.
            "well_supported_cutoff": _DEFAULT_WELL_SUPPORTED_CUTOFF,
        },
        "guards": {
            "forbidden_safe_phrases": cfg.guards.forbidden_safe_phrases,
            "toxicity_keywords": cfg.guards.toxicity_keywords,
            "route_terms": cfg.guards.route_terms,
        },
        "languages": {
            "supported": cfg.languages.supported,
            "default": cfg.corpus.default_language,
        },
        "prompts": {
            "refusal_by_lang": cfg.prompts.refusal_by_lang,
            "disclosure_by_lang": cfg.prompts.disclosure_by_lang,
            "safety_route_by_lang": cfg.prompts.safety_route_by_lang,
            "nontoxic_caveat_by_lang": cfg.prompts.nontoxic_caveat_by_lang,
            "escalation_card_by_lang": cfg.prompts.escalation_card_by_lang,
            # The localized copy a screen reader announces for each confidence band
            # (EXP-06). Shipped as data so the browser says the same words the server
            # UI says; the band *keys* are stable identifiers and live in code on both
            # sides, exactly like the refusal/disclosure strings above.
            "confidence_band_labels": cfg.prompts.confidence_band_labels,
        },
    }


def settings_digest(cfg: Config) -> str:
    """``sha256:`` over the canonical encoding of :func:`settings_payload`."""
    return f"sha256:{sha256_of_obj(settings_payload(cfg))}"


# ----------------------------------------------------------------------------- corpus


def corpus_root_for(cfg: Config) -> Path:
    """The corpus root the fingerprint is taken over, derived from the config.

    A corpus root is the directory holding ``manifest.yaml`` beside ``processed/`` --
    the layout ``corpus/`` uses and the layout ``corpus install`` writes. The config
    names the two halves separately, so this derives the root from the manifest and then
    insists the config's ``corpus.path`` really is that root's ``processed/``. Without
    that insistence a config pointing the two halves at different trees would be
    fingerprinted over one of them and indexed from the other, and the resulting
    agreement would be an artifact of asking two different questions.
    """
    manifest = Path(cfg.corpus.manifest)
    root = manifest.parent
    processed = root / "processed"
    configured = Path(cfg.corpus.path)
    if not manifest.is_file():
        raise WebBundleError(
            f"corpus manifest not found: {manifest} — the corpus fingerprint is taken "
            "over the manifest and the documents it lists, and neither could be read"
        )
    if not processed.is_dir():
        raise WebBundleError(
            f"{processed} is not a directory, so {root} is not a corpus root and the "
            "fingerprint `sprout corpus diff` reports cannot be taken over it"
        )
    if processed.resolve() != configured.resolve():
        raise WebBundleError(
            f"corpus.path is {configured} but corpus.manifest sits beside {processed}; "
            "the fingerprint and the index would describe two different corpora, so "
            "no comparison between them would mean anything"
        )
    return root


def as_of_bounds(documents: Sequence[Document]) -> tuple[str, str, int]:
    """``(earliest, latest, unmeasurable)`` over the corpus's ``fetch_date`` values.

    Absent, malformed and future dates are all unmeasurable and none of them widen the
    range. A future ``fetch_date`` is the one worth naming: taken at face value it would
    become ``latest`` and the banner would advertise a snapshot from a date that has not
    arrived, which is a broken record rendered as the freshest fact in the corpus.
    """
    today = date.today()
    measurable: list[date] = []
    unmeasurable = 0
    for doc in documents:
        try:
            parsed = date.fromisoformat(doc.fetch_date)
        except (TypeError, ValueError):
            unmeasurable += 1
            continue
        if parsed > today:
            unmeasurable += 1
            continue
        measurable.append(parsed)
    if not measurable:
        return "", "", unmeasurable
    return min(measurable).isoformat(), max(measurable).isoformat(), unmeasurable


def expected_chunk_ids_digest(cfg: Config, documents: Sequence[Document]) -> tuple[int, str]:
    """``(count, digest)`` over the chunk ids the *current* corpus chunks to.

    A chunk id is a hash of the chunk's own text, so this is what an index built from
    this corpus, right now, would contain. Comparing it against the ids inside a
    bundle's ``index.json`` is what distinguishes "the index was copied faithfully" from
    "the index was built from this corpus".
    """
    chunks = build_chunks(cfg, list(documents))
    ids = sorted(chunk.chunk_id for chunk in chunks)
    return len(ids), f"sha256:{sha256_of_obj(ids)}"


def index_chunk_ids_digest(index_path: str | Path) -> tuple[int, str]:
    """``(count, digest)`` over the chunk ids actually present in a built index."""
    path = Path(index_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WebBundleError(f"index not found: {path} — run `make ingest` first") from exc
    except json.JSONDecodeError as exc:
        raise WebBundleError(f"{path} is not valid JSON: {exc}") from exc
    chunks = raw.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise WebBundleError(
            f"{path} carries no chunks, so every comparison against it would be "
            "vacuously true; run `make ingest` to rebuild it"
        )
    ids = sorted(str(chunk.get("chunk_id", "")) for chunk in chunks)
    if any(not chunk_id for chunk_id in ids):
        raise WebBundleError(f"{path} has a chunk with no chunk_id; it cannot be identified")
    return len(ids), f"sha256:{sha256_of_obj(ids)}"


# ------------------------------------------------------------------------- provenance


def build_provenance(cfg: Config, index_path: str | Path) -> BundleProvenance:
    """Compute the provenance an export of ``cfg`` + ``index_path`` would carry.

    :func:`corpus_root_for` runs first and raises when the configured corpus is not on
    disk. That ordering is load-bearing: ``load_corpus`` falls back to the corpus bundled
    inside the installed package when the configured paths are absent, which is right for
    ``sprout ask`` on a fresh install and would be silently wrong here — a mistyped path
    would fingerprint the packaged corpus and record it as this checkout's.
    """
    from .corpus_diff import CorpusDiffError, corpus_fingerprint

    root = corpus_root_for(cfg)
    try:
        fingerprint = corpus_fingerprint(cfg, root)
    except CorpusDiffError as exc:  # pragma: no cover - corpus_root_for pre-checks these
        raise WebBundleError(str(exc)) from exc
    documents = load_corpus(cfg)
    earliest, latest, unmeasurable = as_of_bounds(documents)
    expected_chunks, expected_ids = expected_chunk_ids_digest(cfg, documents)
    index_chunks, index_ids = index_chunk_ids_digest(index_path)
    if (index_chunks, index_ids) != (expected_chunks, expected_ids):
        raise WebBundleError(
            f"{index_path} was not built from the corpus at {root}: it holds "
            f"{index_chunks} chunks ({index_ids}) where this corpus chunks to "
            f"{expected_chunks} ({expected_ids}). Run `make ingest` before exporting — "
            "recording this index's own digest here would certify a stale index as "
            "matching the config beside it"
        )
    return BundleProvenance(
        corpus_fingerprint=fingerprint,
        corpus_documents=len(documents),
        corpus_as_of_earliest=earliest,
        corpus_as_of_latest=latest,
        corpus_dates_unmeasurable=unmeasurable,
        config_sha256=settings_digest(cfg),
        index_sha256=f"sha256:{sha256_of_file(index_path)}",
        index_chunks=index_chunks,
        index_chunk_ids_sha256=index_ids,
    )


def bundle_document(cfg: Config, index_path: str | Path) -> dict[str, Any]:
    """The whole of ``data/config.json``: schema version, provenance, then settings."""
    return {
        "format_version": BUNDLE_FORMAT_VERSION,
        "provenance": build_provenance(cfg, index_path).model_dump(),
        **settings_payload(cfg),
    }


def render_bundle(cfg: Config, index_path: str | Path) -> str:
    """``bundle_document`` as the bytes written to disk: sorted keys, one trailing newline."""
    document = bundle_document(cfg, index_path)
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def read_provenance(bundle_dir: str | Path) -> BundleProvenance:
    """The provenance recorded inside an exported bundle.

    Every way this can fail to produce an answer raises. A bundle exported before the
    provenance block existed is the case worth spelling out: it parses, it is a
    perfectly good bundle for *answering*, and it carries nothing to compare -- so
    reading it as "no mismatches found" would turn the staleness check into a check that
    cannot fail on the artifact it was written for.
    """
    path = Path(bundle_dir) / CONFIG_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WebBundleError(
            f"{path} does not exist, so there is no bundle to check; run `make web-static-bundle`"
        ) from exc
    except json.JSONDecodeError as exc:
        raise WebBundleError(f"{path} is not valid JSON: {exc}") from exc
    version = raw.get("format_version")
    if version != BUNDLE_FORMAT_VERSION:
        raise WebBundleError(
            f"{path} declares format_version {version!r}, not {BUNDLE_FORMAT_VERSION}. "
            "A bundle at an older version records no corpus fingerprint and no config "
            "hash, so nothing about it can be compared; re-export it with "
            "`make web-static-bundle`"
        )
    recorded = raw.get("provenance")
    if not isinstance(recorded, dict) or not recorded:
        raise WebBundleError(
            f"{path} carries no provenance block, so which corpus and which "
            "configuration it was built from is unrecorded and unanswerable"
        )
    try:
        return BundleProvenance.model_validate(recorded)
    except ValueError as exc:
        raise WebBundleError(f"{path}: provenance block is not usable: {exc}") from exc


# ------------------------------------------------------------------------------ check


#: Which fields are compared, and what a mismatch in each one actually means. Written as
#: prose because the reader of a failing gate is trying to decide what to re-run.
_MISMATCH_MEANING: dict[str, str] = {
    "corpus_fingerprint": (
        "the bundle was exported from a different corpus than this checkout has. "
        "`sprout corpus diff` reports the same value for a corpus root, so the two "
        "fingerprints can be compared against a diff report directly"
    ),
    "config_sha256": (
        "config/sprout.yaml changed after this bundle was exported. The browser is "
        "running the old thresholds, deny-lists or prompt strings, which is the "
        "silent abstain-threshold divergence issue #108 found"
    ),
    "index_sha256": "index.json in the bundle is not the bytes `make ingest` wrote",
    "index_chunk_ids_sha256": (
        "the passages in the bundle's index are not the passages this corpus chunks "
        "to — the browser is retrieving from text the corpus no longer contains"
    ),
    "index_chunks": "the bundle's index holds a different number of chunks than this corpus",
    "corpus_documents": "the corpus gained or lost documents after this bundle was exported",
    "corpus_as_of_earliest": "the corpus's earliest fetch_date moved after this export",
    "corpus_as_of_latest": "the corpus's latest fetch_date moved after this export",
    "corpus_dates_unmeasurable": (
        "a different number of documents have an absent, malformed or future "
        "fetch_date than when this bundle was exported"
    ),
}


def check_bundle(bundle_dir: str | Path, cfg: Config, index_path: str | Path) -> list[str]:
    """Every way the exported bundle disagrees with this checkout.

    Returns an empty list only when the bundle exists, declares the current format
    version, carries a complete provenance block, and every recorded field equals the
    value recomputed from ``cfg``, its corpus, and ``index_path``. Raises
    :class:`WebBundleError` when the comparison could not be made at all -- which is a
    failure, not a pass.
    """
    recorded = read_provenance(bundle_dir)
    expected = build_provenance(cfg, index_path)

    problems: list[str] = []
    for field in BundleProvenance.model_fields:
        was, now = getattr(recorded, field), getattr(expected, field)
        if was == now:
            continue
        meaning = _MISMATCH_MEANING.get(field, "this field moved after the export")
        problems.append(f"{field}: bundle says {was!r}, this checkout computes {now!r} — {meaning}")

    bundled_index = Path(bundle_dir) / INDEX_FILE
    if not bundled_index.is_file():
        problems.append(
            f"{bundled_index} does not exist: the bundle records an index but does not "
            "ship one, so the page would have nothing to answer from"
        )
    else:
        shipped = f"sha256:{sha256_of_file(bundled_index)}"
        if shipped != recorded.index_sha256:
            problems.append(
                f"{bundled_index} hashes to {shipped}, but the bundle's own provenance "
                f"records {recorded.index_sha256} — config.json and the index beside it "
                "were not written by the same export"
            )
    return problems


def check_bundle_from_paths(
    bundle_dir: str | Path, config_path: str | Path, index_path: str | Path
) -> list[str]:
    """:func:`check_bundle` with the config loaded from ``config_path``."""
    path = Path(config_path)
    if not path.is_file():
        raise WebBundleError(f"config not found: {path}")
    return check_bundle(bundle_dir, load_config(path), index_path)


def export_bundle(
    config_path: str | Path, index_path: str | Path, out_dir: str | Path
) -> tuple[Path, Path]:
    """Write ``config.json`` and ``index.json`` into ``out_dir``. Returns both paths."""
    cfg = load_config(Path(config_path))
    if cfg.retrieval.embedding_provider != "deterministic":
        raise WebBundleError(
            "retrieval.embedding_provider must be 'deterministic' — the browser port "
            "only implements the offline hashing embedder"
        )
    source_index = Path(index_path)
    if not source_index.is_file():
        raise WebBundleError(f"{source_index} not found — run `make ingest` first.")

    rendered = render_bundle(cfg, source_index)
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    config_dest = destination / CONFIG_FILE
    config_dest.write_text(rendered, encoding="utf-8")
    index_dest = destination / INDEX_FILE
    index_dest.write_bytes(source_index.read_bytes())

    # The provenance names a digest of the index; if the copy did not land byte-for-byte
    # the bundle would ship a claim about a file it does not contain.
    if sha256_of_bytes(index_dest.read_bytes()) != sha256_of_file(source_index):
        raise WebBundleError(  # pragma: no cover - defends against a partial write
            f"{index_dest} does not match {source_index} after copying"
        )
    return config_dest, index_dest
