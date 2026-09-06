"""The declared version, held to the releases that exist.

`pyproject.toml` declares `0.1.0`. `git tag -l` prints nothing: no tag has ever
been cut, `release.yml` has never fired, and nothing has been published to PyPI
(where the name `sprout` belongs to an unrelated library). That is the intended
state and nothing here demands a tag.

Sprout already gets one half of this right, and the reason it does is worth
keeping in front of whoever reads this next. `CITATION.cff` once carried
`date-released: 2026-06-22` for a release that was never cut; it was corrected
on 2026-07-05 to `version: "0.1.0-dev"` with no release date and a comment
explaining what would restore both fields. That correction was prose. Nothing
enforced it, so nothing stopped it happening again — and it happens routinely
across this portfolio: a version bump moves the citation file and a
`date-released` gets invented to sit beside it.

These checks make the correction mechanical, and add the questions it did not
answer:

* does any tag carry the declared version, and if none does, does the
  repository say so where a reader sees it;
* does every restatement of the number agree with `pyproject.toml` — including
  `CITATION.cff`'s deliberate `-dev` marker, whose *base* must still match;
* is the pre-release marker present exactly while it is true.

A missing tag and an unfetched tag are indistinguishable from inside a
checkout, so nothing below concludes "no tag exists" from a checkout that would
not have shown one (`_why_tags_are_unreadable`). Reading an empty tag list out
of a shallow clone and calling it evidence is absence rendered as a value.
`test_ci_fetches_the_tags_these_checks_read` is the other half: without it these
would skip in the run that gates a merge.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

import sprout

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CITATION = ROOT / "CITATION.cff"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

#: The top-level ``version:`` and ``date-released:`` of the citation file,
#: matched line by line rather than parsed so that a commented-out field stays
#: commented out (this file explains itself at length in comments).
CITATION_VERSION = re.compile(r'^version:\s*"?([^"\s#]+)"?\s*$', re.MULTILINE)
CITATION_DATE = re.compile(r'^date-released:\s*"?(\d{4}-\d{2}-\d{2})"?\s*$', re.MULTILINE)

#: A release tag, with or without the ``v``.
RELEASE_TAG = re.compile(r"^v?(\d+\.\d+\.\d+(?:[-+.].+)?)$")

#: The ``**Status:** ...`` paragraph under the summary blockquote.
README_STATUS = re.compile(r"^\*\*Status:\*\*(.*?)(?:\n\n|\Z)", re.MULTILINE | re.DOTALL)

#: The two sentences the README uses to say nothing has been released. Pinned
#: so that cutting a tag makes them false loudly rather than quietly.
README_SAYS_NO_TAG = "no tag has ever been cut yet"
README_SAYS_NOTHING_TO_INSTALL = "There is no release to install"

#: The pre-release marker `CITATION.cff` carries while nothing is tagged.
PRERELEASE_MARKER = "-dev"

#: The sentinel `sprout.__version__` falls back to when the distribution is not
#: installed. It is a labelled unknown, not a version, and must never be read
#: as one — comparing it to the manifest is the whole point.
NOT_INSTALLED = "0.0.0+unknown"


def _manifest_version() -> str:
    manifest = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    version = manifest["project"]["version"]
    assert isinstance(version, str)
    return version


def _git(*args: str) -> str | None:
    """Run git in the checkout. ``None`` means the answer is unavailable."""
    executable = shutil.which("git")
    if executable is None:
        return None
    try:
        done = subprocess.run(  # argv is fixed, the path is resolved, and no shell is used
            [executable, "-C", str(ROOT), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError:  # pragma: no cover - git present but unusable
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def _why_tags_are_unreadable() -> str | None:
    """Why an empty tag list here would prove nothing, or ``None`` if it proves something."""
    if not (ROOT / ".git").exists():
        return f"no .git in {ROOT}: an installed tree carries no tags to read"
    if shutil.which("git") is None:
        return "no git executable on PATH"
    if _git("rev-parse", "--is-inside-work-tree") != "true":
        return "not a git work tree"
    if _git("rev-parse", "--is-shallow-repository") == "true":
        return "shallow checkout: tags are not fetched, so an empty tag list is not evidence"
    if (_git("config", "--get", "remote.origin.tagOpt") or "") == "--no-tags":
        return "clone configured with tagOpt=--no-tags, so tags were never fetched"
    return None


def _release_tags() -> list[str]:
    """Release tags, newest first."""
    listed = _git("tag", "--list", "--sort=-v:refname") or ""
    return [tag for tag in listed.splitlines() if RELEASE_TAG.match(tag.strip())]


def _tag_version(tag: str) -> str:
    matched = RELEASE_TAG.match(tag)
    assert matched is not None, tag
    return matched.group(1)


def _require_readable_tags() -> list[str]:
    reason = _why_tags_are_unreadable()
    if reason is not None:
        pytest.skip(f"cannot measure the repository's tags: {reason}")
    return _release_tags()


def _cited_version() -> str:
    cited: list[str] = CITATION_VERSION.findall(CITATION.read_text(encoding="utf-8"))
    assert len(cited) == 1, f"expected one top-level version: field in CITATION.cff, found {cited}"
    return cited[0]


def test_the_declared_version_is_held_to_the_tags_that_exist() -> None:
    """No tag is a legitimate state here. Not saying so is not."""
    tags = _require_readable_tags()
    declared = _manifest_version()
    readme = README.read_text(encoding="utf-8")

    if not tags:
        assert README_SAYS_NO_TAG in readme, (
            f"pyproject.toml declares {declared} and no tag exists, so no artifact carries "
            f"that version, and README.md no longer says so ({README_SAYS_NO_TAG!r} is gone)"
        )
        assert README_SAYS_NOTHING_TO_INSTALL in readme, (
            f"README.md no longer says {README_SAYS_NOTHING_TO_INSTALL!r}, and no tag exists"
        )
        return

    newest = tags[0]
    assert README_SAYS_NO_TAG not in readme, (
        f"README.md still says {README_SAYS_NO_TAG!r}, and {newest} exists"
    )
    assert declared in {_tag_version(tag) for tag in tags}, (
        f"pyproject.toml declares {declared} and no tag carries it. Newest tag: {newest}. "
        f"Tags: {', '.join(tags)}. Either the declared version is unreleased and the README "
        "has to say so, or the tag is missing."
    )


def test_the_status_line_names_the_version_and_says_it_is_untagged() -> None:
    """The number is otherwise nowhere on the page a reader forms an impression from.

    It lived in `pyproject.toml`, in installed metadata, and in `CITATION.cff`
    behind a `-dev` suffix. A bump could move all three and leave the README
    describing something else.
    """
    tags = _require_readable_tags()
    declared = _manifest_version()

    status_match = README_STATUS.search(README.read_text(encoding="utf-8"))
    assert status_match is not None, "README.md has no `**Status:**` paragraph"
    status = " ".join(status_match.group(1).split())

    assert declared in status, (
        f"pyproject.toml declares {declared} and the README's Status paragraph does not "
        f"name it: {status!r}. Newest tag: {tags[0] if tags else 'none'}."
    )
    if not tags:
        assert "untagged" in status, (
            f"no tag exists, so nothing carries {declared}, and the README's Status "
            f"paragraph does not say it is untagged: {status!r}"
        )
    else:
        assert "untagged" not in status, (
            f"the README's Status paragraph still says untagged, and {tags[0]} exists"
        )


def test_every_restatement_of_the_version_agrees_with_the_manifest() -> None:
    """One source of truth, and the copies of it derived or checked, never asserted."""
    declared = _manifest_version()

    # `sprout.__version__` is read from installed metadata rather than written
    # down (REL-02). The sentinel is a labelled unknown; reading it as a version
    # is the defect class this repository exists to avoid, so name it.
    assert sprout.__version__ != NOT_INSTALLED, (
        "sprout.__version__ is the not-installed sentinel; run `uv sync --locked` so this "
        "check compares a real version rather than a placeholder"
    )
    assert sprout.__version__ == declared

    cited = _cited_version()
    assert cited.split("-")[0].split("+")[0] == declared, (
        f"CITATION.cff states version {cited!r}; pyproject.toml declares {declared}"
    )


def test_the_citation_marks_itself_pre_release_exactly_while_it_is_one() -> None:
    """The 2026-07-05 correction, made mechanical.

    `CITATION.cff` carried `date-released: 2026-06-22` for a release that was
    never cut. It now carries a `-dev` version and no date. Both halves are
    checked here, in both directions: the marker and the missing date are
    required while no tag exists, and forbidden once one does — otherwise the
    first real release ships a citation that still calls itself a draft.
    """
    tags = _require_readable_tags()
    cited = _cited_version()
    dated = CITATION_DATE.findall(CITATION.read_text(encoding="utf-8"))

    if not tags:
        assert cited.endswith(PRERELEASE_MARKER), (
            f"CITATION.cff cites {cited!r} and no tag exists, so nothing carrying that "
            f"version was ever released; it has to keep the {PRERELEASE_MARKER!r} marker"
        )
        assert not dated, (
            f"CITATION.cff carries date-released {dated[0]!r} and no tag exists in this "
            "repository, so it dates a release that was never cut — the exact claim "
            "corrected on 2026-07-05"
        )
        return

    assert not cited.endswith(PRERELEASE_MARKER), (
        f"CITATION.cff still cites {cited!r} as a pre-release, and {tags[0]} exists"
    )
    assert dated, f"CITATION.cff carries no date-released and {tags[0]} exists"


def _jobs(workflow: str) -> dict[str, str]:
    """Split a workflow into its jobs. Cheaper and more robust here than a YAML parse."""
    lines = workflow.splitlines()
    try:
        first = next(i for i, line in enumerate(lines) if line.rstrip() == "jobs:")
    except StopIteration:  # pragma: no cover - a workflow with no jobs
        return {}
    starts = [
        (index, matched.group(1))
        for index in range(first + 1, len(lines))
        if (matched := re.match(r"^  ([A-Za-z0-9_-]+):\s*$", lines[index])) is not None
    ]
    bounds = [*[index for index, _ in starts], len(lines)]
    return {name: "\n".join(lines[bounds[n] : bounds[n + 1]]) for n, (_, name) in enumerate(starts)}


def _runs(body: str, command: str) -> bool:
    """Does this job actually run the command, rather than mention it?

    Comments are prose. Elsewhere in this portfolio a job that only named the
    gate in a comment was pulled into this check's scope by a raw text match.
    """
    lines = body.splitlines()
    return any(command in line for line in lines if not line.lstrip().startswith("#"))


def test_ci_fetches_the_tags_these_checks_read() -> None:
    """Otherwise the tag checks skip in CI and gate nothing.

    `actions/checkout` fetches one commit and no tags by default, which is the
    shape `_why_tags_are_unreadable` refuses to draw a conclusion from. The job
    that runs the suite has to ask for the tags.
    """
    jobs = _jobs(CI_WORKFLOW.read_text(encoding="utf-8"))
    suite = "uv run --locked pytest"
    running = {name: body for name, body in jobs.items() if _runs(body, suite)}
    assert running, ".github/workflows/ci.yml has no job that runs the test suite"
    for name, body in running.items():
        assert "actions/checkout" in body, f"job {name!r} runs the suite without a checkout"
        assert "fetch-depth: 0" in body, (
            f"job {name!r} checks out shallow, so tests/test_release_versions.py skips there"
        )
        assert "fetch-tags: true" in body, (
            f"job {name!r} does not fetch tags, so tests/test_release_versions.py skips there"
        )


def test_the_changelog_records_the_declared_version_when_it_is_released() -> None:
    """A tagged version with no changelog section is a release with no record of its changes.

    Untagged, everything belongs under ``## [Unreleased]`` and this asserts
    nothing — pre-writing a dated heading for a release that has not happened is
    the same defect in a different file.
    """
    tags = _require_readable_tags()
    if not tags:
        return
    declared = _manifest_version()
    heading = f"## [{declared}]"
    assert heading in CHANGELOG.read_text(encoding="utf-8"), (
        f"{tags[0]} exists and CHANGELOG.md has no {heading!r} section"
    )
