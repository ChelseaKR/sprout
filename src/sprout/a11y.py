"""Structural WCAG checks and the non-chat transcript renderer.

Two jobs: (1) a deterministic structural accessibility check used both as a merge gate
on the chat UI and as a *self-check* the HTML eval report must pass before it is written
(we never emit an inaccessible accessibility tool); (2) render the static, paginated
"transcript" alternate view of questions/answers/citations for users who cannot operate a
live chat. These are structural checks (lang, title, heading order, alt text, table
captions/scope, link text, no positive tabindex) — they complement, never replace, the
axe/pa11y browser gates and the screen-reader walkthrough.
"""

from __future__ import annotations

import html
import re
from itertools import pairwise

_TAG_LANG = re.compile(r"<html[^>]*\blang=", re.IGNORECASE)
_TITLE = re.compile(r"<title>\s*\S", re.IGNORECASE)
_H1 = re.compile(r"<h1[ >]", re.IGNORECASE)
_HEADINGS = re.compile(r"<h([1-6])[ >]", re.IGNORECASE)
_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_IMG_ALT = re.compile(r"\balt=", re.IGNORECASE)
_TABLE = re.compile(r"<table\b", re.IGNORECASE)
_CAPTION = re.compile(r"<caption[ >]", re.IGNORECASE)
_TH_SCOPE = re.compile(r"<th\b(?![^>]*\bscope=)", re.IGNORECASE)
_POSITIVE_TABINDEX = re.compile(r'tabindex=["\']?[1-9]', re.IGNORECASE)
_EMPTY_LINK = re.compile(r"<a\b[^>]*>\s*</a>", re.IGNORECASE)


class AccessibilityError(ValueError):
    """Raised when rendered HTML fails its structural accessibility check."""


def _check_document(doc: str) -> list[str]:
    problems: list[str] = []
    if not _TAG_LANG.search(doc):
        problems.append("html element is missing a lang attribute (WCAG 3.1.1)")
    if not _TITLE.search(doc):
        problems.append("document has no non-empty <title> (WCAG 2.4.2)")
    if not _H1.search(doc):
        problems.append("document has no <h1> (WCAG 1.3.1 / 2.4.6)")
    return problems


def _check_headings(doc: str) -> list[str]:
    levels = [int(m.group(1)) for m in _HEADINGS.finditer(doc)]
    for prev, cur in pairwise(levels):
        if cur > prev + 1:
            return [f"heading level jumps from h{prev} to h{cur} (WCAG 1.3.1)"]
    return []


def _check_tables_and_images(doc: str) -> list[str]:
    problems: list[str] = []
    if any(not _IMG_ALT.search(img) for img in _IMG.findall(doc)):
        problems.append("an <img> is missing an alt attribute (WCAG 1.1.1)")
    if _TABLE.search(doc):
        if not _CAPTION.search(doc):
            problems.append("a <table> has no <caption> (WCAG 1.3.1)")
        if _TH_SCOPE.search(doc):
            problems.append("a <th> is missing a scope attribute (WCAG 1.3.1)")
    return problems


def _check_focus_and_links(doc: str) -> list[str]:
    problems: list[str] = []
    if _POSITIVE_TABINDEX.search(doc):
        problems.append("positive tabindex disrupts focus order (WCAG 2.4.3)")
    if _EMPTY_LINK.search(doc):
        problems.append("a link has no discernible text (WCAG 2.4.4)")
    return problems


def check_html(doc: str) -> list[str]:
    """Return structural WCAG violations in ``doc`` (empty list = pass)."""
    return [
        *_check_document(doc),
        *_check_headings(doc),
        *_check_tables_and_images(doc),
        *_check_focus_and_links(doc),
    ]


def assert_accessible(doc: str) -> None:
    """Raise :class:`AccessibilityError` if ``doc`` has any structural violation."""
    problems = check_html(doc)
    if problems:
        raise AccessibilityError("; ".join(problems))


def render_transcript(
    title: str, entries: list[tuple[str, str, list[str]]], lang: str = "en"
) -> str:
    """Render a static, accessible transcript: (question, answer, citations) triples."""
    rows: list[str] = []
    for i, (question, answer, citations) in enumerate(entries, start=1):
        cites = "".join(f"<li>{html.escape(c)}</li>" for c in citations)
        cite_block = f"<h3>Sources</h3><ul>{cites}</ul>" if citations else ""
        rows.append(
            f'<article aria-labelledby="q{i}">'
            f'<h2 id="q{i}">Q{i}. {html.escape(question)}</h2>'
            f"<p>{html.escape(answer)}</p>{cite_block}</article>"
        )
    body = "\n".join(rows)
    return (
        f'<!doctype html><html lang="{html.escape(lang)}"><head>'
        f'<meta charset="utf-8"><title>{html.escape(title)}</title></head>'
        f"<body><main><h1>{html.escape(title)}</h1>{body}</main></body></html>"
    )
