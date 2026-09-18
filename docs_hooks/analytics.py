"""Put the GA4 loader and the footer opt-out on every MkDocs page.

The owner decided on 2026-09-17 to run Google Analytics 4 on every public site in the
portfolio (ADR 0023). The loader, the measurement ID and every guard live in one file,
``web-static/public/analytics.js``, which the Pages workflow publishes at the site root
next to the reference page. This hook adds the two things each handbook page needs to
use it: a ``<script src="/analytics.js">`` in ``<head>``, and the footer block that
discloses GA and carries the "Opt out of analytics" control the loader wires.

It changes nothing else. The 404 page is rendered from the theme's template rather
than as a page, so it carries neither. Registered as a mkdocs hook in ``mkdocs.yml``;
it runs at build time only.
"""

from __future__ import annotations

from typing import Any

#: The loader, from the site root. ``web-static/public/`` is copied over ``site/``
#: after ``mkdocs build``, so the file is there when the page is served.
LOADER = '<script src="/analytics.js"></script>'

#: The footer sentence, shared word for word with ``web-static/public/index.html``;
#: ``tests/test_analytics.py`` holds the two equal.
NOTE = (
    "Pages on this site use Google Analytics 4 to count visits, with its advertising "
    "features off. It does not load when your browser sends Global Privacy Control or "
    "Do Not Track, and it never sees a question you type into the reference."
)

#: The control the loader wires. ``hidden`` until then, so a browser without
#: JavaScript, which never runs GA either, is never shown a button that does nothing.
CHOICE = (
    '<p class="analytics-choice" data-analytics-choice hidden>'
    '<button type="button" class="analytics-toggle">Opt out of analytics</button> '
    '<span class="analytics-status" role="status"></span></p>'
)

FOOTER = (
    '<div class="md-footer-meta md-typeset analytics-footer">'
    '<div class="md-footer-meta__inner md-grid"><div class="md-copyright">'
    f'<p>{NOTE} <a href="/privacy/">Privacy: what it records and how to turn it off</a>.</p>'
    f"{CHOICE}</div></div></div>"
)


def add_analytics(html: str) -> str:
    """``html`` with the loader in ``<head>`` and the block at the end of the footer.

    Idempotent, and it refuses a page it cannot place both on rather than shipping one
    half: a loader with no control would give a reader no way to opt out on that page.
    """
    if LOADER in html:
        return html
    head_end = html.find("</head>")
    footer_end = html.rfind("</footer>")
    if head_end == -1 or footer_end == -1 or footer_end < head_end:
        raise ValueError("analytics hook: page has no </head> or no </footer> to place GA in")
    html = html[:footer_end] + FOOTER + html[footer_end:]
    return html[:head_end] + LOADER + html[head_end:]


def on_post_page(output: str, page: Any, config: Any) -> str:
    """mkdocs ``on_post_page`` event: the rendered page, with GA added."""
    return add_analytics(output)
