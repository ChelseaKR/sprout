"""The sitemap's ``<lastmod>`` hook, and the one way it could quietly lie again.

mkdocs stamped every entry with the build date. The hook replaces that with the
date of the commit that last changed each page. The failure mode worth testing is
not "git returned nothing" -- that case is visible and handled -- but the one where
git returns something confident and wrong: in a shallow clone ``git log -1 -- <path>``
answers for every path with the tip commit's date, because relative to no parent the
single grafted commit introduces the whole tree.

So the control here is a real depth-1 clone of a real repository whose file was last
changed months before its tip. It asserts both halves: that the naive per-path
question does come back with the tip's date in that clone (the trap is live, not
hypothetical), and that the hook refuses to date anything there instead of publishing
it.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

_MODULE = importlib.util.spec_from_file_location(
    "sitemap_lastmod",
    Path(__file__).resolve().parent.parent / "docs_hooks" / "sitemap_lastmod.py",
)
assert _MODULE is not None and _MODULE.loader is not None
sitemap_lastmod = importlib.util.module_from_spec(_MODULE)
_MODULE.loader.exec_module(sitemap_lastmod)

#: When the page changed, and when the repository last did. Two different days, so a
#: date derived from the tip is distinguishable from a date derived from the page.
PAGE_CHANGED = "2026-05-01"
REPO_TIP = "2026-09-07"

_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def _run(repo: Path, *args: str, when: str | None = None) -> None:
    env = dict(_IDENTITY)
    if when is not None:
        env["GIT_AUTHOR_DATE"] = f"{when}T12:00:00+00:00"
        env["GIT_COMMITTER_DATE"] = f"{when}T12:00:00+00:00"
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**_environ(), **env},
    )


def _environ() -> dict[str, str]:
    import os

    return dict(os.environ)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose one page last changed months before its tip commit."""
    if shutil.which("git") is None:  # pragma: no cover - git is present in CI and locally
        pytest.skip("git is not available")
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    _run(root, "init", "-q", "-b", "main")
    (root / "docs" / "page.md").write_text("# Page\n", encoding="utf-8")
    _run(root, "add", "docs/page.md")
    _run(root, "commit", "-q", "-m", "add the page", when=PAGE_CHANGED)
    # A later commit that does not touch the page. This is what makes the shallow
    # answer wrong rather than accidentally right.
    (root / "README.md").write_text("unrelated\n", encoding="utf-8")
    _run(root, "add", "README.md")
    _run(root, "commit", "-q", "-m", "something else entirely", when=REPO_TIP)
    return root


def test_a_page_is_dated_from_the_commit_that_changed_it(repo: Path) -> None:
    assert sitemap_lastmod.history_refusal(repo) is None
    assert sitemap_lastmod.last_changed(repo, repo / "docs" / "page.md") == PAGE_CHANGED


def test_an_uncommitted_page_has_no_date_rather_than_a_guess(repo: Path) -> None:
    new = repo / "docs" / "draft.md"
    new.write_text("# Draft\n", encoding="utf-8")
    assert sitemap_lastmod.last_changed(repo, new) is None


def test_a_tree_that_is_not_a_checkout_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    (plain / "docs").mkdir(parents=True)
    refusal = sitemap_lastmod.history_refusal(plain)
    assert refusal is not None
    assert "not a git checkout" in refusal


def test_a_shallow_clone_answers_with_the_wrong_date_and_is_refused(
    repo: Path, tmp_path: Path
) -> None:
    """The control. Both halves of it matter and neither implies the other."""
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", repo.as_uri(), str(shallow)],
        check=True,
        capture_output=True,
        env=_environ(),
    )

    # Half one: the trap is real. Asked directly, git answers for a path it has no
    # history for, with the tip's date, and nothing about the reply is malformed.
    naive = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", "docs/page.md"],
        cwd=shallow,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert naive == REPO_TIP != PAGE_CHANGED

    # Half two: the hook asks whether the checkout can answer before it asks anything
    # else, so that reply never reaches a sitemap.
    refusal = sitemap_lastmod.history_refusal(shallow)
    assert refusal is not None
    assert "shallow" in refusal
    assert "fetch-depth: 0" in refusal


def test_the_written_sitemap_is_compared_against_the_derived_dates(tmp_path: Path) -> None:
    """The failure this comparison exists for, measured rather than imagined.

    With the template override removed and the hook left in place, the build printed
    `52 of 53 pages state when they last changed` while the file it had just written
    carried the build date on all 53. The count was right about the hook and wrong
    about the artifact, and only the artifact is published.
    """
    build_date = "2026-09-13"
    derived = [PAGE_CHANGED, REPO_TIP]
    complaints = sitemap_lastmod.disagreements([build_date] * 3, derived)
    assert len(complaints) == 1
    assert "carries 3 date(s) but this hook derived 2" in complaints[0]
    assert f"Published and not derived: {build_date}" in complaints[0]


def test_dates_that_match_are_not_a_complaint() -> None:
    assert sitemap_lastmod.disagreements([REPO_TIP, PAGE_CHANGED], [PAGE_CHANGED, REPO_TIP]) == []


def test_an_unwritten_sitemap_is_not_read_as_agreement(tmp_path: Path) -> None:
    """A missing artifact is not a matching one; it is nothing to compare."""
    assert sitemap_lastmod.published_dates(tmp_path) is None


def test_published_dates_are_read_back_out_of_the_written_file(tmp_path: Path) -> None:
    (tmp_path / "sitemap.xml").write_text(
        "<urlset>"
        f"<url><loc>https://example.invalid/</loc><lastmod>{PAGE_CHANGED}</lastmod></url>"
        "<url><loc>https://example.invalid/undated/</loc></url>"
        "</urlset>",
        encoding="utf-8",
    )
    assert sitemap_lastmod.published_dates(tmp_path) == [PAGE_CHANGED]
