"""Pairwise numeric-cadence contradiction probe (EXP-02).

Retrieval can turn up two passages that give genuinely different care cadences for the
same action — "water every 7 days" in one source, "water every 14 days" in another —
and, until this module, the pipeline had no concept of that: whichever chunk the
generator happened to quote just won, silently. This module re-scans every *retrieved*
sibling chunk (not only the one a rendered sentence quotes) for a same-action cadence
that disagrees with it, and returns both citations so the answer can say "sources
differ" instead of picking a winner.

Scope is deliberately narrow (see docs/ideation/03-expansions.md, EXP-02 "Risks/deps"):
only numeric-cadence conflicts are probed. A general polarity-contradiction probe over
arbitrary claims would over-fire on legitimate seasonal or per-action variation
("water weekly in summer" vs "biweekly in winter" are both true, not a conflict), so
this stays scoped to same-action numeric disagreement between a pair of chunks and
never attempts to reconcile *why* two sources differ.

Toxicity routing: this probe only ever compares two chunks that share a ``topic``
(see ``numeric_cadence_conflicts``), so if either side of a conflict is a toxicity
passage, the *other* side is too — meaning the existing topic-based safety routing in
``answer.py`` (``toxicity_cited``) already fires whenever a disagreement touches
toxicity content, and disagreement never bypasses it.
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import AnswerSentence, Citation, RetrievedChunk, SourceDisagreement
from .text import extract_cadences


def _citation_from_chunk(retrieved: RetrievedChunk) -> Citation:
    chunk = retrieved.chunk
    return Citation(
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        title=chunk.title,
        source=chunk.source,
        quote=chunk.text,
        license=chunk.license,
        fetch_date=chunk.fetch_date,
        url=chunk.url,
    )


def _sibling_conflicts(
    sentence: AnswerSentence,
    base_mentions: list[tuple[str, float, str]],
    rc: RetrievedChunk,
    seen: set[tuple[str, str, str]],
) -> list[SourceDisagreement]:
    """Cadence conflicts between one rendered sentence and one sibling chunk."""
    sibling_mentions = extract_cadences(rc.chunk.text)
    if not sibling_mentions:
        return []
    out: list[SourceDisagreement] = []
    for action, days, mention in base_mentions:
        for sib_action, sib_days, sib_mention in sibling_mentions:
            if action != sib_action or days == sib_days:
                continue
            pair = tuple(sorted((sentence.chunk_id, rc.chunk.chunk_id)))
            key = (pair[0], pair[1], action)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                SourceDisagreement(
                    action=action,
                    mention_a=mention,
                    citation_a=sentence.citation,
                    mention_b=sib_mention,
                    citation_b=_citation_from_chunk(rc),
                )
            )
    return out


def numeric_cadence_conflicts(
    sentences: Sequence[AnswerSentence],
    retrieved: Sequence[RetrievedChunk],
) -> tuple[SourceDisagreement, ...]:
    """Find same-action, different-value cadence conflicts between rendered sentences
    and their sibling retrieved chunks.

    For each rendered sentence, every *other* retrieved chunk that shares its topic is
    checked for a cadence mention of the same care action but a different day-value.
    One :class:`SourceDisagreement` is returned per (chunk pair, action), deduplicated
    so a conflict found from either side is only reported once. Never averages the two
    values and never drops one in favour of the other — both citations are always
    carried together.
    """
    topic_by_chunk_id = {rc.chunk.chunk_id: rc.chunk.topic for rc in retrieved}
    out: list[SourceDisagreement] = []
    seen: set[tuple[str, str, str]] = set()

    for sentence in sentences:
        base_topic = topic_by_chunk_id.get(sentence.chunk_id)
        if base_topic is None:
            continue
        base_mentions = extract_cadences(sentence.text)
        if not base_mentions:
            continue
        for rc in retrieved:
            if rc.chunk.chunk_id == sentence.chunk_id or rc.chunk.topic != base_topic:
                continue
            out.extend(_sibling_conflicts(sentence, base_mentions, rc, seen))
    return tuple(out)
