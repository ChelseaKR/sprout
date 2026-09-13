"""Say what each page is, and what it is about, in a form a machine can read.

Every published page here already carries a title, a description, an absolute
self-referencing canonical and a full card. All of that describes the page to a
*person* — a search result rendered for someone who is already looking. None of
it states, in any vocabulary a machine reads, what the page is or what the thing
on it is. A crawler learned the name of a page and nothing else.

This hook adds one ``application/ld+json`` block per page holding four nodes:
the site, this page, the trail to it, and Sprout itself as the software the page
is about. The ``@id`` values are stable across pages, so a crawler that reads
two of them sees one site and one piece of software rather than fifty of each.

**Nothing here is written for the block.** ``name`` is the page's own title as
mkdocs has it, ``description`` is the description :mod:`page_description` already
derived from the page's opening paragraph, ``url`` is the canonical mkdocs
computes, the site and repository addresses come out of ``mkdocs.yml``, and the
trail comes out of the nav. The block cannot say something the page does not,
because it is not given anything the page does not already have.

**What is deliberately not here.** There is no ``Dataset`` node and no DCAT.
A dataset descriptor is not a description, it is an invitation: it exists so
dataset search engines and open-data catalogs harvest what it names and list it
as a dataset of record, and a listing is much easier to acquire than to
withdraw. Whether this portfolio solicits that over its corpora is an open
question with an owner's name on it, and adding the markup quietly is not how it
gets answered. Saying "this page is about a piece of software" asks for none of
it. ``sprout.site_meta`` fails the build if the harvest vocabulary appears.

Registered as a mkdocs hook in ``mkdocs.yml``. It runs at build time only and
touches nothing at runtime. It sends nothing anywhere: the block is inert data,
not a script, and no analytics, beacon, pixel or cookie is involved.
"""

from __future__ import annotations

import json
import re
from html import unescape as html_unescape
from typing import Any

#: The language the page declares about itself. Read back off the rendered page
#: rather than taken from config, so the block and the `<html lang>` a reader's
#: browser acts on cannot be two different answers.
_HTML_LANG = re.compile(r"<html\b[^>]*\blang\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_HEAD_END = "</head>"


def _identifiers(config: Any) -> tuple[str, str, str]:
    """The three stable ``@id`` bases, all from ``mkdocs.yml``."""
    site = config.site_url.rstrip("/") + "/"
    return site, f"{site}#website", f"{config.repo_url}#software"


def _breadcrumb(page: Any, site: str, crumb_id: str) -> dict[str, Any]:
    """The nav trail to this page, taken from the nav rather than restated.

    A hand-listed trail is the defect this file exists to avoid: move a page in
    the nav and the trail goes on describing where it used to be. ``ancestors``
    is mkdocs' own answer to "what is above this", nearest first, so it is
    reversed and the page itself added on the end.

    Some ancestors are nav sections rather than pages — "Accessibility" and
    "Cards" group other pages and have no address of their own. A ``ListItem``
    is allowed to name a position without naming a thing, which is the honest
    rendering: the section is really in the trail and really has nowhere to go.
    """
    trail: list[tuple[str, str]] = [("Home", site)]
    for ancestor in reversed(list(page.ancestors)):
        url = getattr(ancestor, "canonical_url", "") or ""
        trail.append((html_unescape(ancestor.title), url))
    trail.append((html_unescape(page.title), page.canonical_url))

    items = []
    for position, (name, url) in enumerate(trail, start=1):
        item: dict[str, Any] = {
            "@type": "ListItem",
            "position": position,
            "name": name,
        }
        if url:
            item["item"] = url
        items.append(item)
    return {"@type": "BreadcrumbList", "@id": crumb_id, "itemListElement": items}


def graph(page: Any, config: Any, lang: str) -> dict[str, Any]:
    """The whole block, as data, so a test can build it without a build."""
    site, website_id, software_id = _identifiers(config)
    canonical = page.canonical_url
    # Titles and descriptions reach this hook as HTML: mkdocs keeps a title as
    # it was written in the markdown, entities and all, and `page_description`
    # escapes what it writes because mkdocs-material interpolates the value
    # straight into a double-quoted attribute. JSON carries text, not markup,
    # and has no entities to decode, so a node reading `Personas &amp; Interviews`
    # says a different thing from the page and says it to the only reader that
    # cannot tell. Both are decoded here, so the node carries the sentence a
    # reader's browser actually shows.
    description = html_unescape(page.meta.get("description", "") or "")

    webpage: dict[str, Any] = {
        "@type": "WebPage",
        "@id": f"{canonical}#webpage",
        "url": canonical,
        "name": html_unescape(page.title),
        "description": description,
        "inLanguage": lang,
        "isPartOf": {"@id": website_id},
        "about": {"@id": software_id},
    }

    nodes: list[dict[str, Any]] = [
        {
            "@type": "WebSite",
            "@id": website_id,
            "url": site,
            "name": config.site_name,
            "inLanguage": lang,
        },
        webpage,
    ]

    # The home page is the root of the trail, so it has no trail. Emitting a
    # one-item breadcrumb pointing at itself would be a claim about structure
    # where there is none.
    if not page.is_homepage:
        crumb_id = f"{canonical}#breadcrumb"
        webpage["breadcrumb"] = {"@id": crumb_id}
        nodes.append(_breadcrumb(page, site, crumb_id))

    nodes.append(
        {
            "@type": "SoftwareApplication",
            "@id": software_id,
            "name": config.site_name,
            "description": config.site_description,
            "url": site,
            "sameAs": config.repo_url,
            "inLanguage": lang,
        }
    )
    return {"@context": "https://schema.org", "@graph": nodes}


def block(payload: dict[str, Any]) -> str:
    """The payload as an element body that cannot end its own element.

    ``</script`` inside a JSON string closes the element as far as an HTML
    parser is concerned, whatever JSON thinks of it. Escaping the three
    characters that can begin markup keeps the block inert without changing
    what it decodes to, which is all any consumer of this actually reads.
    """
    return (
        json.dumps(payload, ensure_ascii=False, indent=2)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def on_post_page(output: str, page: Any, config: Any) -> str:
    """Add the page's structured data to its head."""
    if _HEAD_END not in output or not getattr(page, "canonical_url", ""):
        # No head to add it to, or no address to be about. Both are conditions
        # `sprout site-check` reports on the built tree; silently inventing a
        # node for a page in that state would hide the real problem behind a
        # well-formed claim.
        return output
    found = _HTML_LANG.search(output)
    lang = found.group(1) if found else ""
    if not lang:
        return output
    payload = graph(page, config, lang)
    element = f'<script type="application/ld+json">\n{block(payload)}\n</script>\n'
    return output.replace(_HEAD_END, element + _HEAD_END, 1)
