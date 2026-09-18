"""State when each page last changed, or state nothing.

mkdocs fills every ``<lastmod>`` in ``sitemap.xml`` from
``mkdocs.utils.get_build_date()`` -- the day the build ran. On a site rebuilt from
every push to ``main`` that makes all 53 entries read today's date, on every page,
every day: a document untouched since August advertises itself as changed this
morning, and will advertise itself as changed tomorrow morning too. ``lastmod`` is
the one element in a sitemap that is a factual claim about the content, and that
claim was about the CI runner.

This hook replaces it with the date of the commit that last changed the page's own
source file, and -- where there is no such commit -- with nothing at all.
``<lastmod>`` is optional in the sitemaps protocol, so an omitted element is a
valid sitemap that says nothing false, which a stamped-today one is not.

It pairs with ``theme_overrides/sitemap.xml``, which emits the element only for a
page this hook could date. Nothing here writes a date; every date it publishes is
one git already recorded.

WHY IT ASKS WHETHER THE CHECKOUT CAN ANSWER, NOT WHETHER AN ANSWER ARRIVED

``git log -1 --format=%cs -- <path>`` does not fail in a depth-1 clone. It answers,
for *every* path, with the tip commit's date: relative to no parent, the single
grafted commit introduces the whole tree. Nothing about that reply is malformed, so
a reader that asks and then sanity-checks what came back cannot tell it from a real
answer -- it would quietly reinstate the build date under a new name, on every page
at once, which is the defect this hook exists to remove. So the first question is
whether this checkout has the history to answer at all
(``git rev-parse --is-shallow-repository``), asked once, before any date is read.

TWO VOICES

An omission is the honest artifact and a silent one. So the build says out loud how
many entries it could date and names the routes it could not, and
``sprout site-check`` (a merge gate, and a step of ``docs-pages``) reads the
published sitemap and fails when it carries no date at all -- which is what a
shallow checkout, or a lost ``fetch-depth: 0``, actually produces.

AND THE COUNT IS CHECKED AGAINST THE FILE, NOT TRUSTED

This hook computes dates; ``theme_overrides/sitemap.xml`` publishes them. Those are
two things, and the first cannot see the second. Measured while writing this: with
the template override removed and the hook left in place, the build still printed
``52 of 53 pages state when they last changed`` while the file it had just written
carried the build date on all 53 -- a reassuring number beside the exact artifact it
was wrong about. So ``on_post_build`` reads the sitemap back and fails the build
unless the dates in it are precisely the dates computed here.

Registered as a mkdocs hook in ``mkdocs.yml``. It runs at build time only, shells
out to git only, and touches nothing at runtime.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger("mkdocs.hooks.sitemap_lastmod")

#: What a published ``<lastmod>`` is allowed to look like. ``git log --format=%cs``
#: emits exactly this, and ``sprout site-check`` refuses anything else, so a page
#: that declares its own ``lastmod`` in front matter is held to the same shape.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Source pages whose built HTML is not what the site serves at that address, so
#: their source's history is not the history of the published document.
#:
#: ``docs-pages`` (and ``make site-check``) copy ``web-static/public/`` over the
#: mkdocs output after the build, so ``/`` is served by the zero-server reference
#: surface and not by ``docs/index.md``. Dating that URL from ``docs/index.md``
#: would publish a change date for a document nobody receives. The reference
#: surface is assembled from the TypeScript sources *and* the exported corpus
#: bundle, so no single source file's history describes it either: the honest
#: answer for this one URL is no answer.
_NOT_THE_PUBLISHED_DOCUMENT = frozenset({"index.md"})

#: Timeout on any single git call. A hung git must not hang a docs build.
_GIT_TIMEOUT_SECONDS = 30.0

#: Populated in ``on_files`` and read in ``on_page_markdown``: ``src_uri`` -> date.
#: Reset on every build so ``mkdocs serve``'s rebuilds cannot carry a stale map.
_DATES: dict[str, str] = {}

#: Every documentation page this build considered, dated or not. Kept so the count
#: printed at the end has a denominator that is the pages, not a second walk of the
#: docs directory that could disagree with the one mkdocs actually built from.
_PAGES: list[str] = []

#: Why no page could be dated, or ``None`` when at least one could. Reported once,
#: in ``on_post_build``, so the build says it rather than leaving a silent gap.
_REFUSAL: str | None = None


def _git(repo: Path, *args: str) -> str | None:
    """One git command's stdout, or ``None`` when git could not answer it."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def history_refusal(repo: Path) -> str | None:
    """Why this checkout cannot date a page, or ``None`` when it can.

    Asked once per build, before any date is read, for the reason in this module's
    header: in a shallow clone the per-path question has a confident wrong answer
    rather than no answer.
    """
    inside = _git(repo, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        return (
            "this tree is not a git checkout, so no page has a recorded change date. "
            "The sitemap will carry no <lastmod> at all."
        )
    if _git(repo, "rev-parse", "--is-shallow-repository") != "false":
        return (
            "this is a shallow (depth-limited) checkout. `git log -1 -- <path>` answers "
            "for every path in one, with the tip commit's date, so asking it here would "
            "stamp today's date on every page under a different name. Check out with "
            "`fetch-depth: 0` (actions/checkout) or `git fetch --unshallow`. The sitemap "
            "will carry no <lastmod> at all until then."
        )
    return None


def last_changed(repo: Path, source: Path) -> str | None:
    """The committer date of the commit that last changed ``source``.

    Committer date rather than author date: it is when the change reached this
    branch, which is when the page a reader fetches actually moved. A file with no
    commit touching it -- newly added and not yet committed, or generated into the
    docs tree by a build step -- has no change date here, and gets none.
    """
    answer = _git(repo, "log", "-1", "--format=%cs", "--", str(source))
    if not answer or not _ISO_DATE.match(answer):
        return None
    return answer


def on_files(files: Any, config: Any) -> Any:
    """Date every documentation page once, before any of them is rendered."""
    global _REFUSAL
    _DATES.clear()
    _PAGES.clear()
    docs_dir = Path(config["docs_dir"])
    repo = docs_dir.parent
    _REFUSAL = history_refusal(repo)
    _PAGES.extend(sorted(file.src_uri for file in files.documentation_pages()))
    if _REFUSAL is not None:
        return files
    for source in _PAGES:
        if source in _NOT_THE_PUBLISHED_DOCUMENT:
            continue
        date = last_changed(repo, docs_dir / source)
        if date is not None:
            _DATES[source] = date
    return files


def on_page_markdown(markdown: str, page: Any, config: Any, files: Any) -> str:
    """Hand the page its own change date, if this checkout knows one.

    A page that states its own ``lastmod`` in front matter keeps it: the page is
    closer to its content than its file's history is, and the published value is
    held to the same format by ``sprout site-check`` either way.
    """
    if not page.meta.get("lastmod"):
        date = _DATES.get(page.file.src_uri)
        if date is not None:
            page.meta["lastmod"] = date
    return markdown


#: Pulls every ``<lastmod>`` out of the written sitemap. A regex and not an XML
#: parser, for the reason ``sprout.site_meta`` gives: this is a file the build just
#: wrote, and a gate that parses XML is still a gate that parses XML.
_PUBLISHED_LASTMOD = re.compile(r"<lastmod>\s*([^<]*?)\s*</lastmod>")


def published_dates(site_dir: Path) -> list[str] | None:
    """Every ``<lastmod>`` in the sitemap this build wrote, or ``None`` if there is none."""
    sitemap = site_dir / "sitemap.xml"
    if not sitemap.is_file():
        return None
    return _PUBLISHED_LASTMOD.findall(sitemap.read_text(encoding="utf-8"))


def on_post_build(config: Any) -> None:
    """Say how many entries carry a date, name the ones that do not, and check the file.

    A number with no denominator beside it is the shape this whole change exists to
    remove, so the count of pages that could be dated is printed next to the count of
    pages there were -- and then read back out of the artifact, because the count and
    the artifact are produced by different code and only one of them is published.
    """
    if _REFUSAL is not None:
        log.warning(
            "sitemap <lastmod>: 0 of %d pages state when they last changed -- %s",
            len(_PAGES),
            _REFUSAL,
        )
    else:
        log.info(
            "sitemap <lastmod>: %d of %d pages state when they last changed",
            len(_DATES),
            len(_PAGES),
        )
        for source in _PAGES:
            if source not in _DATES:
                log.info("sitemap <lastmod>: no recorded change date for %s", source)

    published = published_dates(Path(config["site_dir"]))
    if published is None:
        log.warning("sitemap <lastmod>: no sitemap.xml was written, so nothing was checked")
        return
    for complaint in disagreements(published, sorted(_DATES.values())):
        log.warning("sitemap <lastmod>: %s", complaint)


def disagreements(published: list[str], computed: list[str]) -> list[str]:
    """Every way the written sitemap's dates are not the dates this hook derived.

    Compared as multisets, which is the comparison that catches the failure actually
    observed: a template that ignores this hook and falls back to the build date
    publishes one date, repeated once per URL, while the hook holds many. Comparing
    only the counts would miss it on a day when the two happen to be equal in number.
    """
    if sorted(published) == sorted(computed):
        return []
    extra = sorted(set(published) - set(computed))
    missing = sorted(set(computed) - set(published))
    complaint = (
        f"the sitemap this build wrote carries {len(published)} date(s) but this hook "
        f"derived {len(computed)}; the published dates are not the derived ones"
    )
    if extra:
        complaint += f". Published and not derived: {', '.join(extra)}"
    if missing:
        complaint += f". Derived and not published: {', '.join(missing)}"
    return [complaint]
