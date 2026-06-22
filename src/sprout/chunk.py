"""Split documents into retrievable passages, chunked by care topic.

Processed corpus files are Markdown with ``## <topic>`` sections (watering, light,
toxicity, ...). We chunk along those topic boundaries and then pack whole sentences into
word-bounded windows with sentence-level overlap, so a chunk never ends mid-sentence —
which matters because the generator quotes whole sentences verbatim. The leading ``# H1``
title is dropped (the title comes from the manifest, not the body).
"""

from __future__ import annotations

import re

from .determinism import sha256_of_text
from .models import Chunk, Document
from .text import split_sentences

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-") or "general"


def _sections(text: str, default_topic: str) -> list[tuple[str, str]]:
    """Parse Markdown into (topic, body) pairs, splitting on ``## `` headings."""
    sections: list[tuple[str, str]] = []
    current = default_topic
    buf: list[str] = []

    def flush() -> None:
        body = " ".join(line.strip() for line in buf if line.strip())
        if body.strip():
            sections.append((current, body.strip()))

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            current = line[3:].strip()
            buf = []
        elif line.startswith("# "):
            continue  # H1 title comes from the manifest
        else:
            buf.append(line)
    flush()
    return sections


def _windows(sentences: list[str], max_words: int, overlap_words: int) -> list[str]:
    """Pack whole sentences into <=max_words windows with sentence-level overlap."""
    windows: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        words = len(sentence.split())
        if current and count + words > max_words:
            windows.append(" ".join(current))
            # Carry trailing sentences as overlap into the next window.
            carry: list[str] = []
            carry_words = 0
            for s in reversed(current):
                sw = len(s.split())
                if carry_words + sw > overlap_words:
                    break
                carry.insert(0, s)
                carry_words += sw
            current = carry
            count = carry_words
        current.append(sentence)
        count += words
    if current:
        windows.append(" ".join(current))
    return windows


def chunk_document(doc: Document, max_words: int, overlap_words: int) -> list[Chunk]:
    """Chunk a document into topic-aligned, sentence-bounded passages."""
    chunks: list[Chunk] = []
    for topic, body in _sections(doc.text, doc.topic):
        topic_slug = slugify(topic)
        for i, window in enumerate(_windows(split_sentences(body), max_words, overlap_words)):
            chunk_id = sha256_of_text(f"{doc.doc_id}:{topic_slug}:{i}:{window}")[:12]
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    doc_id=doc.doc_id,
                    title=doc.title,
                    source=doc.source,
                    text=window,
                    language=doc.language,
                    topic=topic_slug,
                    source_name=doc.source_name,
                    url=doc.url,
                    license=doc.license,
                    fetch_date=doc.fetch_date,
                )
            )
    return chunks
