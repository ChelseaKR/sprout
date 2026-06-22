"""Sprout — a grounded, evaluated, multilingual plant-care assistant.

The public surface is intentionally small. Most users drive Sprout through the
``sprout`` CLI or the HTTP server; library users build a :class:`~sprout.config.Config`
and call :class:`~sprout.answer.Assistant`. The eval harness lives in ``sprout.eval``.
"""

from __future__ import annotations

from .answer import Assistant
from .config import Config, load_config
from .models import Answer, AnswerSentence, Chunk, Citation, Document, RetrievedChunk
from .store import VectorStore

__version__ = "0.1.0"

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
