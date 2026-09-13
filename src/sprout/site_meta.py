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
* ``robots.txt`` exists and advertises the sitemap at the origin;
* every ``<loc>`` in ``sitemap.xml`` resolves to a file the build actually
  wrote, and every built page appears in the sitemap;
* every ``<lastmod>`` in ``sitemap.xml`` is a well-formed ``YYYY-MM-DD`` date that
  is not in the future, and at least one entry carries one. ``<lastmod>`` is
  optional, so an entry without one is fine and a page this build could not date
  is meant to have none -- but a sitemap in which *nothing* is dated means the
  build had no history to read (a shallow checkout, a lost ``fetch-depth: 0``),
  and that is a silent regression to exactly the state this gate was added for.

It reads only the built tree. It makes no network call, here or anywhere.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from html import unescape as html_unescape
from pathlib import Path
from urllib.parse import urlsplit

__all__ = ["check_site", "lastmod_coverage", "page_url"]

# Read with a regex rather than an XML parser. The file is one this build just
# wrote, but a gate that parses XML is still a gate that parses XML, and the
# project's SAST rules are right to say so; nothing here needs a parser to find
# the addresses in a urlset.
_URLSET = re.compile(r"<urlset\b", re.IGNORECASE)
_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)
_URL_ENTRY = re.compile(r"<url>(.*?)</url>", re.IGNORECASE | re.DOTALL)
_LASTMOD = re.compile(r"<lastmod>\s*(.*?)\s*</lastmod>", re.IGNORECASE | re.DOTALL)

#: The one shape a published ``<lastmod>`` may take here. The sitemaps protocol
#: allows a full W3C datetime as well, and the builder emits a date, so anything
#: else in the file is a value that came from somewhere this gate does not know
#: about and has not checked.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# Both of these are quote-aware on purpose. A description is prose, and prose has
# apostrophes and angle brackets in it: a naive `[^>]*` tag pattern stops early on
# the first `>` inside an attribute, and a naive `["']([^"']*)["']` value pattern
# read `content="Sprout's value..."` as the single word `Sprout`.
_TAG = re.compile(r"""<(?:meta|link)\b(?:[^>"']|"[^"]*"|'[^']*')*>""", re.IGNORECASE)
_ATTR = re.compile(r"""\b([a-zA-Z:_-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")

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


def _entries(text: str) -> list[tuple[str, str | None]]:
    """Each ``<url>`` in a sitemap as its address and its ``<lastmod>``, if any."""
    found: list[tuple[str, str | None]] = []
    for entry in _URL_ENTRY.finditer(text):
        block = entry.group(1)
        loc = _LOC.search(block)
        if loc is None:
            continue
        stamp = _LASTMOD.search(block)
        found.append(
            (html_unescape(loc.group(1)), html_unescape(stamp.group(1)) if stamp else None)
        )
    return found


def lastmod_coverage(root: Path) -> tuple[int, int]:
    """How many published sitemap entries state when the page last changed, of how many.

    Both numbers, never just the first. A build that dated nothing prints the same
    reassuring line as one that dated everything unless the denominator is beside it.
    """
    sitemap = root / "sitemap.xml"
    if not sitemap.is_file():
        return (0, 0)
    entries = _entries(sitemap.read_text(encoding="utf-8"))
    return (sum(1 for _, stamp in entries if stamp), len(entries))


def _check_lastmod(entries: list[tuple[str, str | None]], today: date) -> list[str]:
    """Every way a published ``<lastmod>`` is not a fact about the content.

    ``<lastmod>`` is optional, and that is the point: a page whose change date this
    build could not read is supposed to carry none, because an omitted element says
    nothing while a stamped one is a claim. So a missing element is never a problem
    here and a malformed or impossible one always is.

    A date in the future is treated as broken rather than fresh, for the reason a
    future timestamp always is: it is a wrong clock or a wrong record, and every
    "is this recent" comparison it is fed into answers yes forever.
    """
    problems: list[str] = []
    dated = 0
    for url, stamp in entries:
        if stamp is None:
            continue
        dated += 1
        if not _ISO_DATE.match(stamp):
            problems.append(
                f"sitemap lastmod for {url} is {stamp!r}, which is not a YYYY-MM-DD date"
            )
            continue
        try:
            stamped = date.fromisoformat(stamp)
        except ValueError:
            problems.append(f"sitemap lastmod for {url} is {stamp!r}, which is not a real date")
            continue
        if stamped > today:
            problems.append(
                f"sitemap lastmod for {url} is {stamp}, which is in the future. "
                "A page cannot have changed after now; that is a clock or a record, "
                "not freshness."
            )
    if entries and dated == 0:
        problems.append(
            f"not one of the {len(entries)} sitemap entries says when its page last "
            "changed. <lastmod> is optional per entry on purpose, but none at all means "
            "the build could read no history -- a shallow checkout, or a lost "
            "`fetch-depth: 0` -- rather than a site with nothing to date."
        )
    return problems


def _check_sitemap(root: Path, origin: str, pages: list[Path], today: date) -> list[str]:
    sitemap = root / "sitemap.xml"
    if not sitemap.is_file():
        return ["sitemap.xml was not published"]
    text = sitemap.read_text(encoding="utf-8")
    if not _URLSET.search(text):
        return ["sitemap.xml is not a urlset"]
    entries = _entries(text)
    listed = [url for url, _ in entries]
    if not listed:
        return ["sitemap.xml lists no URL at all"]

    problems = []
    built = {page_url(origin, page, root) for page in pages}
    for url in listed:
        if url not in built:
            problems.append(f"sitemap lists {url}, which this build did not write")
    for url in sorted(built - set(listed)):
        problems.append(f"{url} was built but is in neither the sitemap nor a noindex")
    problems.extend(_check_lastmod(entries, today))
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


def check_site(root: Path, origin: str, *, today: date | None = None) -> list[str]:
    """Every problem with the published metadata of the built site at ``root``.

    ``origin`` is a bare https origin with no trailing slash. Returns an empty
    list when the site's claims about where its pages live are all true.

    ``today`` is the day the sitemap's dates are read against, and exists so a test
    can pin it. It defaults to the real one.
    """
    origin = origin.rstrip("/")
    today = today or date.today()
    pages = _indexable(sorted(root.rglob("*.html")), root)
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

    problems.extend(_check_robots(root, origin))
    problems.extend(_check_sitemap(root, origin, pages, today))
    return problems
