"""Give each documentation page a meta description in its own words.

mkdocs-material writes ``<meta name="description">`` from a page's front matter
and falls back to ``site_description`` when the page declares none. Every page
here declared none, so all 52 published URLs shipped one identical sentence
about the project, which describes the site rather than the page and tells a
search engine nothing about which of them answers a question.

The fix does not write new copy. It takes the page's own opening paragraph,
which is the sentence the page already leads with, and trims it to a length a
result listing will render. A page that wants to say something else says it in
front matter, and this leaves it alone.

Registered as a mkdocs hook in ``mkdocs.yml``. It runs at build time only and
touches nothing at runtime.
"""

from __future__ import annotations

import html
import re
from typing import Any

#: Where a result listing stops rendering. Trimming happens at a word boundary
#: before this, so a description is never cut mid-word.
_LIMIT = 155

_SETEXT = re.compile(r"^[=-]{2,}\s*$")
_INLINE = (
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),  # images carry no sentence
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links keep their text
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),
    (re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)"), r"\1"),
    (re.compile(r"<[^>]+>"), ""),
    (re.compile(r"\s+"), " "),
)


def _read(markdown: str) -> tuple[str, list[str], list[str]]:
    """The page's H1, its prose paragraphs, and its quoted paragraphs.

    Quoted text is kept separately and used only as a fallback, because a
    blockquote is usually a caveat about the page rather than a summary of it.
    Some pages here -- the generated eval, smoke and corpus reports -- open on a
    table and have no prose at all, and a caveat is still better than nothing.
    """
    heading = ""
    prose: list[str] = []
    quoted: list[str] = []
    current: list[str] = []
    into = prose
    fenced = False

    def flush() -> None:
        nonlocal current
        if current:
            into.append(" ".join(current))
            current = []

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        if stripped.startswith("# ") and not heading:
            heading = stripped[2:].strip()
        if stripped.startswith(">"):
            flush()
            into = quoted
            current.append(stripped.lstrip("> ").strip())
        elif _is_prose(stripped):
            current.append(stripped)
        else:
            flush()
            into = prose
    flush()
    return heading, prose, quoted


def _is_prose(stripped: str) -> bool:
    """Whether a line is part of a paragraph rather than structure around one.

    Headings, admonitions, lists, tables and setext underlines are all structure.
    A bullet marker is only a marker when a space follows it: a paragraph may
    perfectly well open on **bold text**.
    """
    if not stripped:
        return False
    if stripped.startswith(("#", "!!!", "???", "|")):
        return False
    if stripped[:2] in ("- ", "* ", "+ ", ": "):
        return False
    if stripped[0].isdigit() and stripped[1:3] in (". ", ") "):
        return False
    return not (_SETEXT.match(stripped) or set(stripped) <= {"-", "=", "_"})


def _clean(text: str) -> str:
    for pattern, replacement in _INLINE:
        text = pattern.sub(replacement, text)
    return text.strip()


def _trim(text: str) -> str:
    """The longest prefix that fits, ending on a sentence if one ends in time."""
    if len(text) <= _LIMIT:
        return text
    window = text[: _LIMIT + 1]
    sentence = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
    if sentence >= _LIMIT // 2:
        return window[: sentence + 1].strip()
    return window[: window.rfind(" ")].rstrip(" ,;:").strip() + "..."


#: Shorter than this and a description says nothing a listing can use, so the
#: next candidate is added to it rather than the first one being accepted alone.
_FLOOR = 40


def describe(markdown: str) -> str:
    """The page's own opening words, as a meta description.

    Prose first, then a quoted caveat, then the page's H1, taking each in turn
    until there is enough to read. Nothing here is written for the page; every
    word of it is already on the page. Empty when the page has no words at all.
    """
    heading, prose, quoted = _read(markdown)
    parts: list[str] = []
    for candidate in (*prose, *quoted, heading):
        cleaned = _clean(candidate)
        if not cleaned:
            continue
        parts.append(cleaned)
        joined = " ".join(parts)
        if len(joined) >= _FLOOR:
            return _trim(joined)
    return _trim(" ".join(parts)) if parts else ""


def on_page_markdown(markdown: str, page: Any, config: Any, files: Any) -> str:
    """Set the page's description from its own opening paragraph, if it has none."""
    if not page.meta.get("description"):
        described = describe(markdown)
        if described:
            # mkdocs-material interpolates this straight into a double-quoted
            # attribute with no escaping of its own, and prose carries quotation
            # marks: unescaped, an ADR quoting its own model card closed the
            # attribute early and left the rest of the sentence as stray markup.
            page.meta["description"] = html.escape(described, quote=True)
    return markdown
