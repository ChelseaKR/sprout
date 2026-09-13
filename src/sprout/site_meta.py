"""Structural checks on the metadata of the published site.

The same shape as :mod:`sprout.a11y`: a pure function over rendered HTML and a
built directory, returning a list of problems, wired to a CLI command and a make
target. It is deliberately not part of ``a11y.check_html`` -- a missing canonical
is not a WCAG failure, and mixing the two would let one gate's message stand for
the other's rule.

What it checks is the small set of claims a published page makes about *where it
is*, because a wrong one is worse than a missing one:

* every page carries a self-referencing ``<link rel="canonical">`` on the site's
  own origin, over https, with no query or fragment;
* every page carries a non-empty ``<title>`` and ``<meta name="description">``,
  and no two pages share either;
* a page that declares any OpenGraph or Twitter tag declares the whole set, and
  its ``og:title``/``og:description``/``og:url`` repeat what the page itself
  says rather than a second set written for a card;
* a declared ``og:image``/``twitter:image`` is absolute on this origin, carries
  alt text, and resolves to a file the build actually wrote -- an unfurler caches
  whatever it got, so a card naming a missing file is a permanently blank one;
* every link a page makes to this site -- relative, or written against this
  origin in full -- names a file the build actually wrote;
* ``robots.txt`` exists and advertises the sitemap at the origin;
* every ``<loc>`` in ``sitemap.xml`` resolves to a file the build actually
  wrote, and every built page appears in the sitemap.

It reads only the built tree. It makes no network call, here or anywhere.
"""

from __future__ import annotations

import re
from collections import defaultdict
from html import unescape as html_unescape
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

__all__ = ["check_site", "page_url"]

# Read with a regex rather than an XML parser. The file is one this build just
# wrote, but a gate that parses XML is still a gate that parses XML, and the
# project's SAST rules are right to say so; nothing here needs a parser to find
# the addresses in a urlset.
_URLSET = re.compile(r"<urlset\b", re.IGNORECASE)
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# Both of these are quote-aware on purpose. A description is prose, and prose has
# apostrophes and angle brackets in it: a naive `[^>]*` tag pattern stops early on
# the first `>` inside an attribute, and a naive `["']([^"']*)["']` value pattern
# read `content="Sprout's value..."` as the single word `Sprout`.
_TAG = re.compile(r"""<(?:meta|link)\b(?:[^>"']|"[^"]*"|'[^']*')*>""", re.IGNORECASE)
_ATTR = re.compile(r"""\b([a-zA-Z:_-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
# The elements that ask a browser for another address. Built the same quote-aware
# way as `_TAG`, so an apostrophe in an attribute cannot end the match early.
_LINKING = re.compile(
    r"""<(?:a|area|link|img|script|source|iframe)\b(?:[^>"']|"[^"]*"|'[^']*')*>""",
    re.IGNORECASE,
)

#: A page declaring one of these declares all of them. A half-written card is a
#: card a crawler fills in from somewhere else.
_SOCIAL = (
    "og:type",
    "og:site_name",
    "og:url",
    "og:title",
    "og:description",
    "twitter:card",
    "twitter:title",
    "twitter:description",
)


def _attributes(tag: str) -> dict[str, str]:
    return {name.lower(): double or single for name, double, single in _ATTR.findall(tag)}


def _metadata(doc: str) -> tuple[dict[str, str], list[str]]:
    """Every ``name=``/``property=`` meta and every ``rel="canonical"`` href."""
    values: dict[str, str] = {}
    canonicals: list[str] = []
    for tag in _TAG.finditer(doc):
        attrs = _attributes(tag.group(0))
        key = attrs.get("name") or attrs.get("property")
        if key and "content" in attrs:
            values[key.lower()] = attrs["content"].strip()
        if attrs.get("rel", "").lower() == "canonical":
            canonicals.append(attrs.get("href", "").strip())
    return values, canonicals


def _title(doc: str) -> str:
    found = _TITLE.search(doc)
    return " ".join(found.group(1).split()) if found else ""


def page_url(origin: str, page: Path, root: Path) -> str:
    """The address a built page answers on, as mkdocs and GitHub Pages serve it.

    ``<dir>/index.html`` answers on ``<dir>/``; the root's ``index.html``
    answers on the bare origin with a trailing slash. Any other name answers on
    itself. A canonical naming ``index.html`` would publish a second address for
    a page that already has one.
    """
    relative = page.relative_to(root).as_posix()
    if relative == "index.html":
        return f"{origin}/"
    if relative.endswith("/index.html"):
        return f"{origin}/{relative[: -len('index.html')]}"
    return f"{origin}/{relative}"


def _check_canonical(name: str, canonicals: list[str], expected: str) -> list[str]:
    if not canonicals:
        return [f"{name}: no <link rel=canonical>"]
    if len(canonicals) > 1:
        return [f"{name}: {len(canonicals)} canonical links; a page has one address"]
    found = canonicals[0]
    if found != expected:
        return [f"{name}: canonical is {found!r}, but the page answers on {expected!r}"]
    parsed = urlsplit(found)
    problems = []
    if parsed.scheme != "https":
        problems.append(f"{name}: canonical is not https: {found!r}")
    if parsed.query or parsed.fragment:
        problems.append(f"{name}: canonical carries a query or fragment: {found!r}")
    return problems


def _check_social(
    name: str, values: dict[str, str], title: str, url: str, root: Path, origin: str
) -> list[str]:
    declared = [key for key in _SOCIAL if key in values]
    if not declared:
        return []
    problems = [f"{name}: declares {key} nowhere" for key in _SOCIAL if key not in values]
    for key, expected, what in (
        ("og:title", title, "the page title"),
        ("twitter:title", title, "the page title"),
        ("og:description", values.get("description", ""), "the meta description"),
        ("twitter:description", values.get("description", ""), "the meta description"),
        ("og:url", url, "the canonical address"),
    ):
        if key in values and values[key] != expected:
            problems.append(f"{name}: {key} does not match {what}")
    problems.extend(_check_card(name, values, root, origin))
    return problems


#: Every card tag that must name a file this build actually wrote.
_CARD_IMAGES = ("og:image", "twitter:image")


def _check_card(name: str, values: dict[str, str], root: Path, origin: str) -> list[str]:
    """A declared card image must be same-origin, absolute, and really published.

    An unfurler fetches this URL once and caches whatever came back, so a card
    pointing at a file the build did not write degrades to the blank grey box the
    tag was added to prevent — and does it silently, because nothing on the page
    is broken. The same-origin rule was already here; what was missing is the half
    that costs nothing to check and is the half that actually goes wrong.

    Alt text is required alongside, for the same reason the images on these pages
    carry it: a screen reader announcing a shared link reads the card's alt text,
    and this project's card is almost entirely words.
    """
    problems: list[str] = []
    for key in _CARD_IMAGES:
        if key not in values:
            continue
        value = values[key]
        if not value.startswith(f"{origin}/"):
            problems.append(
                f"{name}: {key} is {value!r}, which is not an absolute URL on {origin}. "
                "A relative card image resolves against the site doing the sharing."
            )
            continue
        published = root / value[len(origin) + 1 :]
        if not published.is_file():
            problems.append(
                f"{name}: {key} names {value!r}, which this build did not write. "
                "The card would unfurl empty."
            )
    if any(key in values for key in _CARD_IMAGES):
        problems.extend(
            f"{name}: {key} is declared with no {key}:alt"
            for key in _CARD_IMAGES
            if key in values and not values.get(f"{key}:alt", "").strip()
        )
    return problems


#: Script and style bodies are text, not markup. A template string inside one can
#: hold a whole `<a href=...>`, and a gate that read it would invent failures no
#: reader can meet.
_INERT_BODY = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)

#: Attributes that carry an address this site is responsible for resolving.
_LINK_ATTRS = ("href", "src")
#: Prefixes that address something other than a path on this site.
_OFFSITE = ("http://", "https://", "//", "mailto:", "tel:", "data:", "javascript:", "#")


def _link_targets(doc: str, origin: str) -> list[str]:
    """Every same-site address a page asks the reader's browser to follow.

    A link written against this origin in full is reduced to its path, so it is
    checked the same way a relative one is. Fragments and queries are dropped:
    what is being checked is whether the file at the other end exists.
    """
    targets: list[str] = []
    for tag in _LINKING.finditer(_INERT_BODY.sub(" ", doc)):
        attrs = _attributes(tag.group(0))
        for attr in _LINK_ATTRS:
            if attr not in attrs:
                continue
            value = html_unescape(attrs[attr]).strip()
            if value.startswith(f"{origin}/"):
                value = value[len(origin) :]
            if not value or value.lower().startswith(_OFFSITE):
                continue
            targets.append(value.split("#", 1)[0].split("?", 1)[0])
    return [target for target in targets if target]


def _resolves(target: str, page: Path, root: Path) -> bool:
    """Whether ``target``, read from ``page``, names something the build wrote."""
    if target.startswith("/"):
        resolved = PurePosixPath(target)
    else:
        resolved = PurePosixPath("/") / page.relative_to(root).as_posix()
        resolved = resolved.parent / target
    parts: list[str] = []
    for part in resolved.parts[1:]:
        if part == "..":
            if not parts:
                # Escapes the published tree. Nothing above the site root is
                # served, so this address is one no reader can reach.
                return False
            parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    published = root.joinpath(*parts) if parts else root
    if published.is_dir():
        return (published / "index.html").is_file()
    return published.is_file()


def _check_links(pages: list[Path], root: Path, origin: str) -> list[str]:
    """Every same-site link on a published page must name a published file.

    The failure this exists for leaves no mark on the page that carries it: the
    markup is well formed, the build is green, and the only symptom is the 404 the
    reader meets after clicking. It reached this site because the docs are written
    to be read in the repository, where ``../src/sprout/answer.py`` resolves, and
    are published at an address where it does not.
    """
    problems: list[str] = []
    checked = 0
    for page in pages:
        name = page.relative_to(root).as_posix()
        for target in _link_targets(page.read_text(encoding="utf-8"), origin):
            checked += 1
            if not _resolves(target, page, root):
                problems.append(f"{name}: links {target!r}, which this build did not write")
    if not checked:
        # A sweep that read no link proves nothing, and would go on proving
        # nothing for as long as whatever emptied it stayed broken.
        return ["no page links anything on this site; the link sweep read nothing"]
    return problems


def _check_robots(root: Path, origin: str) -> list[str]:
    robots = root / "robots.txt"
    if not robots.is_file():
        return ["robots.txt was not published, so nothing advertises the sitemap"]
    lines = [line.strip() for line in robots.read_text(encoding="utf-8").splitlines()]
    if f"Sitemap: {origin}/sitemap.xml" not in lines:
        return [f"robots.txt does not advertise {origin}/sitemap.xml"]
    problems = []
    for line in lines:
        directive, _, value = line.partition(":")
        if directive.strip().lower() not in {"allow", "disallow"}:
            continue
        path = value.strip()
        if path not in {"", "/"} and not (root / path.lstrip("/")).exists():
            problems.append(f"robots.txt names {path}, which this site does not serve")
    return problems


def _check_sitemap(root: Path, origin: str, pages: list[Path]) -> list[str]:
    sitemap = root / "sitemap.xml"
    if not sitemap.is_file():
        return ["sitemap.xml was not published"]
    text = sitemap.read_text(encoding="utf-8")
    if not _URLSET.search(text):
        return ["sitemap.xml is not a urlset"]
    listed = [html_unescape(loc) for loc in _LOC.findall(text)]
    if not listed:
        return ["sitemap.xml lists no URL at all"]

    problems = []
    built = {page_url(origin, page, root) for page in pages}
    for url in listed:
        if url not in built:
            problems.append(f"sitemap lists {url}, which this build did not write")
    for url in sorted(built - set(listed)):
        problems.append(f"{url} was built but is in neither the sitemap nor a noindex")
    return problems


def _indexable(pages: list[Path], root: Path) -> list[Path]:
    """Pages offered for indexing. One that says `noindex` is taken at its word.

    ``404.html`` is not one of them: the host serves it in place of a page that
    is not there, never at its own address, so it has no address to be canonical
    about and nothing should list it.
    """
    kept = []
    for page in pages:
        if page.relative_to(root).as_posix() == "404.html":
            continue
        values, _ = _metadata(page.read_text(encoding="utf-8"))
        if "noindex" not in values.get("robots", ""):
            kept.append(page)
    return kept


def check_site(root: Path, origin: str) -> list[str]:
    """Every problem with the published metadata of the built site at ``root``.

    ``origin`` is a bare https origin with no trailing slash. Returns an empty
    list when the site's claims about where its pages live are all true.
    """
    origin = origin.rstrip("/")
    built = sorted(root.rglob("*.html"))
    pages = _indexable(built, root)
    if not pages:
        return [f"{root} holds no indexable page, so this checked nothing"]

    problems: list[str] = []
    titles: dict[str, list[str]] = defaultdict(list)
    descriptions: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        name = page.relative_to(root).as_posix()
        doc = page.read_text(encoding="utf-8")
        values, canonicals = _metadata(doc)
        title = _title(doc)
        url = page_url(origin, page, root)

        if not title:
            problems.append(f"{name}: no non-empty <title>")
        else:
            titles[title].append(name)
        description = values.get("description", "")
        if not description:
            problems.append(f"{name}: no non-empty <meta name=description>")
        else:
            descriptions[description].append(name)

        problems.extend(_check_canonical(name, canonicals, url))
        problems.extend(_check_social(name, values, title, url, root, origin))

    for shared, names in sorted(titles.items()):
        if len(names) > 1:
            problems.append(f"{len(names)} pages share the title {shared!r}: {names[0]} ...")
    for shared, names in sorted(descriptions.items()):
        if len(names) > 1:
            problems.append(
                f"{len(names)} pages share one description: {names[0]} ... ({shared[:60]!r})"
            )

    problems.extend(_check_links(built, root, origin))
    problems.extend(_check_robots(root, origin))
    problems.extend(_check_sitemap(root, origin, pages))
    return problems
