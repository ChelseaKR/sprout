"""Does the published reference actually work with the network off?

The fourth hard rule is offline by default, and the browser reference is the
one surface where it depends on a list somebody typed. ``service-worker.js``
carries a ``SHELL`` array naming every asset to precache, and the build emits
its modules from ``web-static/src/*.ts``. Nothing connected the two, so the
list could fall behind the build silently -- and it did: ``topics.ts`` was
added in the secret-scanner commit, ``answer.ts`` imports ``./topics.js``, and
the array written in the deploy commit never learned about it.

Two failure modes, and they are asymmetric
------------------------------------------

**A required asset missing from the list** leaves the page online-only for that
module. The worker's ``fetch`` handler intercepts nothing outside
``SHELL_URLS``, so offline the request goes to the network, fails, and the
module graph never resolves. The page loads and cannot answer.

**A listed asset the build did not write is worse, and less obvious.**
``cache.addAll()`` is atomic: one 404 rejects the whole call, the ``install``
handler's ``waitUntil`` rejects with it, and the worker never activates. A
single stale line therefore turns off offline support *entirely* -- not for
that asset, for everything -- and the page keeps working perfectly for anyone
online, which is everyone who tests it.

So both directions are checked, and the check refuses to pass on nothing: an
absent worker, an unparseable or empty ``SHELL``, and an unbuilt asset tree are
each reported rather than read as agreement. A gate whose input can go missing
without complaint is the shape this repository keeps finding in other people's
code.

Pure function over a built directory. No network, here or anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["check_offline_shell", "required_entries", "shell_entries"]

#: The worker file, relative to the built reference surface.
WORKER = "service-worker.js"

#: Directories whose every file is part of the offline surface: the compiled
#: modules the page imports, and the corpus bundle it answers from. Derived by
#: listing them, never by repeating their contents here -- repeating them would
#: reproduce in this file the exact defect it exists to catch.
ASSET_DIRS = ("assets", "data")

#: Files at the root of the reference surface that the page needs before it can
#: run at all. ``./`` is the scope root and resolves to ``index.html``; it is
#: matched against the directory rather than against a file of that name.
ROOT_ASSETS = ("index.html", "app.js", "styles.css", "manifest.webmanifest")

_SHELL_ARRAY = re.compile(r"\bconst\s+SHELL\s*=\s*\[(?P<body>.*?)\]\s*;", re.DOTALL)
_ENTRY = re.compile(r"""["'](?P<path>[^"']+)["']""")


class OfflineShellError(ValueError):
    """The offline shell could not be read, so nothing about it was checked."""


def shell_entries(worker_source: str) -> list[str]:
    """Every path listed in the worker's ``SHELL`` array, in source order.

    Read with a regex rather than by executing the file. The alternative is
    running the published worker's JavaScript to find out what it caches, and a
    gate that evaluates the artifact it is auditing can be talked out of its
    own verdict.
    """
    match = _SHELL_ARRAY.search(worker_source)
    if match is None:
        raise OfflineShellError(
            f"no `const SHELL = [...]` array found in {WORKER}; the precache list could "
            "not be read, so nothing was compared against the build"
        )
    entries = [entry.group("path") for entry in _ENTRY.finditer(match.group("body"))]
    if not entries:
        raise OfflineShellError(
            f"{WORKER} declares an empty SHELL; an empty precache list caches nothing "
            "and would make every comparison below vacuously true"
        )
    return entries


def required_entries(root: Path) -> set[str]:
    """Every path the page needs offline, derived from what the build wrote."""
    required = {"./"} | {f"./{name}" for name in ROOT_ASSETS}
    for directory in ASSET_DIRS:
        source = root / directory
        if not source.is_dir():
            raise OfflineShellError(
                f"{source} does not exist, so the offline surface was never built and "
                "there is nothing to compare the precache list against"
            )
        files = sorted(path for path in source.iterdir() if path.is_file())
        if not files:
            raise OfflineShellError(
                f"{source} is empty, so the offline surface was never built and this "
                "check would pass over nothing"
            )
        required |= {f"./{directory}/{path.name}" for path in files}
    return required


def _resolves(root: Path, entry: str) -> bool:
    """Does a SHELL entry name something this build actually wrote?"""
    relative = entry.removeprefix("./")
    if relative == "":
        # The scope root. It resolves to the directory's index document.
        return (root / "index.html").is_file()
    return (root / relative).is_file()


def check_offline_shell(root: Path) -> list[str]:
    """Every disagreement between the precache list and the built tree.

    Returns an empty list only when the worker exists, its ``SHELL`` parses to
    a non-empty list, every asset the page needs offline is on it, and every
    entry on it resolves to a file this build wrote.
    """
    worker = root / WORKER
    if not worker.is_file():
        raise OfflineShellError(
            f"{worker} does not exist; the published reference claims to work offline "
            "and there is no service worker to make that true"
        )
    listed = shell_entries(worker.read_text(encoding="utf-8"))
    required = required_entries(root)

    problems: list[str] = []
    for entry in sorted(required - set(listed)):
        problems.append(
            f"{entry} is served by this build but is not in {WORKER}'s SHELL, so with the "
            "network off the page requests it and the request fails"
        )
    for entry in listed:
        if not _resolves(root, entry):
            problems.append(
                f"{WORKER}'s SHELL names {entry}, which this build did not write. "
                "cache.addAll() rejects atomically, so this one entry stops the worker "
                "installing and turns off offline support entirely"
            )
    duplicates = sorted({entry for entry in listed if listed.count(entry) > 1})
    for entry in duplicates:
        problems.append(f"{WORKER}'s SHELL lists {entry} more than once")
    return problems
