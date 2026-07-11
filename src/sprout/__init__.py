"""Sprout — a grounded, evaluated, multilingual plant-care assistant.

The public surface is intentionally small. Most users drive Sprout through the
``sprout`` CLI or the HTTP server; library users build a :class:`~sprout.config.Config`
and call :class:`~sprout.answer.Assistant`. The eval harness lives in ``sprout.eval``.
"""

from __future__ import annotations

from importlib import metadata

from .answer import Assistant
from .config import Config, load_config
from .models import Answer, AnswerSentence, Chunk, Citation, Document, RetrievedChunk
from .store import VectorStore

try:
    # Single source of truth is pyproject.toml's [project].version; derive rather than
    # hand-copy so the two can never silently drift (REL-02, corrected 2026-07-05 — a
    # hand-copied literal here previously duplicated pyproject.toml by luck, not by
    # construction).
    __version__ = metadata.version("sprout")
except metadata.PackageNotFoundError:  # pragma: no cover - only when run uninstalled
    __version__ = "0.0.0+unknown"

__all__ = [
    "Answer",
    "AnswerSentence",
    "Assistant",
    "Chunk",
    "Citation",
    "Config",
    "Document",
    "RetrievedChunk",
    "VectorStore",
    "__version__",
    "load_config",
]
