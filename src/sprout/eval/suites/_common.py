"""Shared helpers for the suites: claim splitting, plant-slug parsing, term checks."""

from __future__ import annotations

import re

from ...text import contains_phrase, split_sentences
from ..dataset import DatasetItem

_PLANT_RE = re.compile(r"([a-z][a-z-]*?)(?:\.[a-z]{2})?\.md", re.IGNORECASE)


def claims(text: str) -> list[str]:
    """Substantive claim sentences of an answer (drops trivially short fragments)."""
    return [s for s in split_sentences(text) if len(s.split()) >= 3]


def plant_slug(citation: str) -> str:
    """Language-invariant plant key from a citation label or source filename.

    'Monstera care — monstera.es.md (as of 2026-05-01)' -> 'monstera'.
    """
    m = _PLANT_RE.search(citation)
    return m.group(1).lower() if m else citation.strip().lower()


def plant_set(citations: list[str]) -> frozenset[str]:
    return frozenset(plant_slug(c) for c in citations)


def has_all(text: str, terms: list[str]) -> bool:
    return all(contains_phrase(text, t) for t in terms)


def has_any(text: str, terms: list[str]) -> bool:
    return any(contains_phrase(text, t) for t in terms)


def response_text(item: DatasetItem) -> str:
    return item.target_response.text if item.target_response else ""


def is_refused(item: DatasetItem) -> bool:
    return bool(item.target_response and item.target_response.refused)


def citations_of(item: DatasetItem) -> list[str]:
    return item.target_response.citations if item.target_response else []
