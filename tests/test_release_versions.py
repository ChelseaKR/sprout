"""The declared version, held to the releases that exist.

A version number no artifact carries is what a version under development is,
and a project is entitled to one for as long as it likes. What both worlds
require is that the repository keep saying which one it is in, and that every
restatement of the number keep agreeing.

This module deliberately states no present-tense fact about whether anything
here has been tagged. It used to: an earlier docstring described the tag list,
the release workflow's run history and the package registry, all in the present
tense, all true on the day it was written. That paragraph is the single hardest
piece of prose in a Python project to keep honest, because nothing reads a
module docstring — and across this portfolio it is exactly where a sentence
about a release outlived the release. Describe the rule; let the checks
describe the day.

`CITATION.cff` once carried `date-released: 2026-06-22` for a release that was
never cut; it was corrected on 2026-07-05 to a `-dev` version with no release
date and a comment explaining what would restore both fields. That correction
was prose, nothing enforced it, and nothing stopped it happening again. These
checks make it mechanical, and add the questions it did not answer:

* does any tag carry the declared version, and if none does, does the
  repository say so where a reader sees it;
* does every restatement of the number agree with `pyproject.toml` — including
  `CITATION.cff`'s deliberate `-dev` marker, whose *base* must still match;
* is the pre-release marker present exactly while it is true;
* and — `test_no_document_says_this_repository_is_untagged_once_it_is` — does
  *every tracked prose file* stop asserting that nothing was released, rather
  than the one file the rule happens to be pinned in.

That last one is the generalisation. The two-directional README rule below is
correct and was applied to a single sentence in a single file; the same fact is
restated in four more tracked files here, and each was written against the code
rather than against the repository, so all four would go stale in the same
instant with nothing to say so.

A missing tag and an unfetched tag are indistinguishable from inside a
checkout, so nothing below draws a conclusion from a checkout that would not
have shown a tag (`_why_tags_are_unreadable`). Reading an empty tag list out of
a shallow clone and calling it evidence is absence rendered as a value.
`test_ci_fetches_the_tags_these_checks_read` is the other half: without it these
would skip in the run that gates a merge.
"""

from __future__ import annotations

import ast
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
    never cut. The rule that replaces that correction is the `-dev` marker and
    the absent date, both checked here in both directions: required for exactly
    as long as no tag carries the declared version, and forbidden once one does
    — otherwise the first real release ships a citation that still calls itself
    a draft.
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


#: Sentences in this tree that assert, in the present tense, that nothing here
#: has been tagged or released. Every one is verbatim from a tracked file, and
#: every one is true today —
#: `test_every_claim_in_the_vocabulary_is_a_sentence_this_repository_wrote`
#: holds the first half of that to a measurement rather than to this comment,
#: because two entries here were not. They were phrasings from a sibling
#: repository (`release.yml has never fired`, `nothing has been published to
#: pypi`), and while they sat in the tuple looking like coverage, the two
#: sentences this project *does* write in `CITATION.cff` — `no git tag has ever
#: been cut`, one word away from the entry below it, and `no release workflow
#: has run` — were matched by nothing at all.
#:
#: An entry also has to be a *sentence* rather than a fragment. `no tag exists`
#: was here and is not any more: this repository writes it four times and every
#: one is a subordinate clause stating the rule (`required while no tag exists,
#: refused once one does`). A denylist cannot tell an assertion from a
#: conditional, so a fragment that short reddens the gate on prose that is
#: correct — on the day a tag is cut, which is the one day this must not cry
#: wolf.
#:
#: This is a DENYLIST, and a denylist's one guarantee is the whole of what it
#: claims: it finds a phrasing somebody has already written here, and it cannot
#: find one nobody has thought of yet. The structural half of the question needs
#: no vocabulary at all and is where the real guarantee lives —
#: `test_the_citation_marks_itself_pre_release_exactly_while_it_is_one` and the
#: two directions of `test_the_declared_version_is_held_to_the_tags_that_exist`
#: compare values against the repository's own tags. This exists because the
#: same fact is *also* stated in prose, in five files, and prose is where a
#: claim about a release outlives the release.
CLAIMS_OF_NO_RELEASE: tuple[str, ...] = (
    README_SAYS_NO_TAG,
    README_SAYS_NOTHING_TO_INSTALL,
    "no tag has ever been cut",
    "no git tag has ever been cut",
    "no release workflow has run",
    "has ever been published to pypi",
    "never been tagged or released",
    "never yet exercised",
)

#: Suffixes worth reading. A lockfile, a captured fixture or a binary does not
#: carry a sentence a reader takes a fact from.
PROSE_SUFFIXES = frozenset({".md", ".cff", ".py", ".toml", ".yml", ".yaml", ".txt"})

#: `CHANGELOG.md` is exempt because its sections are the record of what was
#: true on the day of each entry, not a claim about today; rewriting a shipped
#: section so a past sentence reads true now would destroy the record this
#: check exists to protect. This module is exempt as a *file*, because the
#: tuple above puts every claim in it verbatim and scanning it would only match
#: itself; its **docstrings** are read instead, which is where a stale paragraph
#: would actually sit — and `test_the_claim_vocabulary_is_real_and_not_self_
#: matching` holds them to the same rule, which makes that read a measurement
#: rather than an exemption.
#:
#: Docstrings, plural, and that is the correction. This was `__doc__` alone, so
#: the rule reached one paragraph of eighteen and the other seventeen were prose
#: no reader and no check ever opened — the module docstring's own point about
#: where a stale sentence hides, one level further in. Widening it to every
#: docstring found `_stale_claims` asserting in the present tense that nothing
#: here is tagged.
CLAIM_SCAN_EXEMPT = frozenset({"CHANGELOG.md"})

THIS_FILE = Path(__file__).resolve()

#: Markdown wraps prose, and a wrapped claim is invisible to a substring match:
#: `CHANGELOG.md` carries `There is no release to install` split across two
#: lines behind a `>` quote marker, and only normalising finds it. Measured on
#: this tree: one file's claim is reachable only after this runs.
_LINE_MARKERS = re.compile(r"^\s*(?:[>#*\-]|//)*\s*", re.MULTILINE)


def _normalized(text: str) -> str:
    """Line markers stripped and whitespace collapsed, so a wrap cannot hide a claim."""
    return re.sub(r"\s+", " ", _LINE_MARKERS.sub(" ", text)).lower()


def _claims_in(text: str) -> list[str]:
    normalized = _normalized(text)
    return [claim for claim in CLAIMS_OF_NO_RELEASE if claim.lower() in normalized]


def _tracked_prose_files() -> list[Path]:
    """Every tracked file whose text a reader could take a fact from."""
    listed = _git("ls-files", "-z")
    if listed is None:  # pragma: no cover - git unusable; every caller skips first
        return []
    paths: list[Path] = []
    for name in listed.split("\0"):
        if not name or name in CLAIM_SCAN_EXEMPT:
            continue
        path = ROOT / name
        if path.suffix in PROSE_SUFFIXES and path.is_file():
            paths.append(path)
    return paths


#: Every docstring in this module has to say something true, so every one is
#: read. Below this the walk is not reading the file: an empty string is what a
#: parse that found nothing returns, and it passes every check downstream.
MIN_DOCSTRINGS_IN_THIS_MODULE = 15


def _own_docstrings() -> list[str]:
    """Every docstring in this module: the prose of the one file the scan skips.

    `__doc__` is one of eighteen. The rest are function docstrings, which is
    prose in exactly the sense this whole check is about — nothing reads it, so
    nothing corrects it. Parsing the source rather than walking the module
    object keeps this measuring the file on disk, which is what the scan around
    it measures.
    """
    tree = ast.parse(THIS_FILE.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            text = ast.get_docstring(node, clean=False)
            if text is not None:
                found.append(text)
    return found


def _stale_claims(tags: list[str]) -> list[str]:
    """Tracked prose still saying nothing was released, given the tags that exist.

    Taking the tag list as an argument rather than reading it is what makes the
    scan measurable here. While nothing is tagged the live call returns an empty
    list — which is also what a scan that has stopped finding the tree returns.
    Passing a tag in exercises the same code over the same files, without
    creating one.
    """
    if not tags:
        return []
    stale: list[str] = []
    for path in _tracked_prose_files():
        if path.resolve() == THIS_FILE:
            texts = _own_docstrings()
        else:
            texts = [path.read_text(encoding="utf-8")]
        for text in texts:
            stale.extend(f"{path.relative_to(ROOT)}: {claim!r}" for claim in _claims_in(text))
    return stale


def _claims_this_repository_has_written() -> dict[str, list[str]]:
    """Where each vocabulary entry is actually written, over the tracked tree.

    This module is read through its docstrings for the same reason the scan
    reads it that way: the tuple puts every entry in the file verbatim, so
    reading the file would make every entry vouch for itself — including one
    copied from another repository, which is the case this exists to catch.
    """
    where: dict[str, list[str]] = {claim: [] for claim in CLAIMS_OF_NO_RELEASE}
    for path in [*_tracked_prose_files(), *(ROOT / name for name in sorted(CLAIM_SCAN_EXEMPT))]:
        if not path.is_file():  # pragma: no cover - an exempt name that is not in the tree
            continue
        if path.resolve() == THIS_FILE:
            texts = _own_docstrings()
        else:
            texts = [path.read_text(encoding="utf-8")]
        for text in texts:
            for claim in _claims_in(text):
                where[claim].append(str(path.relative_to(ROOT)))
    return where


def test_the_claim_vocabulary_is_real_and_not_self_matching() -> None:
    """The floor under the scan below, and the reason it may read its own docstrings.

    Three ways the next two checks could pass while examining nothing: an empty
    claim list, a claim list nothing here has ever said, and a scan that has
    stopped finding the tree. The README's own two pinned sentences are in the
    vocabulary by construction, so at least two entries are sentences this
    project really wrote; and none of them is in any docstring in this module,
    which is what makes reading those for this one file a measurement rather
    than a way of exempting it from its own rule.
    """
    assert CLAIMS_OF_NO_RELEASE, "an empty claim list scans every file and finds nothing"
    for pinned in (README_SAYS_NO_TAG, README_SAYS_NOTHING_TO_INSTALL):
        assert pinned in CLAIMS_OF_NO_RELEASE, (
            f"the vocabulary does not cover {pinned!r}, one of the two sentences this "
            "repository already pins in both directions, so it generalises nothing"
        )
    own = _own_docstrings()
    assert len(own) >= MIN_DOCSTRINGS_IN_THIS_MODULE, (
        f"only {len(own)} docstring(s) parsed out of this module: the walk has stopped "
        "reading the file, and no docstring is what it returns either way"
    )
    for text in own:
        assert not _claims_in(text), (
            f"a docstring in this module states, in the present tense, that nothing here has "
            f"been tagged or released: {_claims_in(text)}. This file is exempt as a file, so "
            "nothing else will ever read it, and a docstring is the one piece of prose in a "
            "Python project that nobody opens. Describe the rule, not the day.\n"
            f"{' '.join(text.split())[:400]}"
        )
    assert _claims_in("> no tag has ever\n> been cut yet"), (
        "a claim wrapped across two quoted lines is not found, so the normalisation this "
        "scan depends on has stopped working and every wrapped sentence is invisible to it"
    )
    assert _claims_in("# 1.2.0): no git tag has ever been cut for this project"), (
        "a claim behind a YAML comment marker is not found. `CITATION.cff` states two of "
        "these that way, and they are the two the vocabulary used to miss entirely"
    )


def test_every_claim_in_the_vocabulary_is_a_sentence_this_repository_wrote() -> None:
    """A denylist entry that matches nothing is coverage that is not there.

    Two entries here were phrasings from a sibling repository rather than from
    this tree. They cost nothing to read and they made the tuple eight entries
    long while covering six — and the two sentences they were *meant* to stand
    in for, both in `CITATION.cff`'s header comment, were matched by nothing.
    One of them differs from the entry that was sitting directly above it by a
    single word.

    So every entry has to be observed somewhere in the tracked tree. That is the
    self-limiting refusal the portfolio's exemption lists want and rarely have:
    an entry stops earning its place the moment nothing says it, and the check
    fails until somebody deletes it or fixes the wording.

    `CHANGELOG.md` counts as an observation even though the staleness scan skips
    it, because a phrasing recorded in the changelog is a phrasing this project
    wrote. This module counts only through its docstrings — reading the file
    would let the tuple vouch for itself, which is exactly how the two borrowed
    entries survived.

    (This paragraph does not quote any of the entries, and that is not fussiness:
    the first draft of it did, and the docstring check above went red on the
    correction. A gate that forbids a wording fires on the sentence explaining
    why the wording is forbidden.)
    """
    _require_readable_tags()
    where = _claims_this_repository_has_written()
    unobserved = sorted(claim for claim, files in where.items() if not files)
    assert not unobserved, (
        f"these claim-vocabulary entries appear nowhere in this repository: {unobserved}. "
        "A denylist entry that matches nothing is not coverage; it reads as coverage. Either "
        "the sentence has been corrected — delete the entry — or the wording here is not the "
        "wording the tree uses, in which case the real sentence is going unwatched."
    )


def test_no_document_says_this_repository_is_untagged_once_it_is() -> None:
    """A sentence saying nothing was ever released has to go when something is.

    `README_SAYS_NO_TAG` and `README_SAYS_NOTHING_TO_INSTALL` are pinned in both
    directions — required while no tag exists, refused once one does — and they
    are pinned *in one file*. This is the same two-directional rule applied to
    every tracked prose file, so that the first tag cannot leave four other
    documents asserting it does not exist.

    The other direction (something must say so while nothing is tagged) is
    `test_the_declared_version_is_held_to_the_tags_that_exist`, which is why
    this half only has anything to say once a tag exists.
    """
    tags = _require_readable_tags()
    scanned = _tracked_prose_files()
    assert len(scanned) > 100, (
        f"only {len(scanned)} tracked prose file(s) to read: this scan has stopped finding "
        "the tree, and a scan that reads nothing reports the same clean result as one that "
        "read everything"
    )
    stale = _stale_claims(tags)
    assert not stale, (
        f"{tags[0]} exists, and these still say nothing here has ever been released: "
        f"{'; '.join(stale)}. Tags carried: {', '.join(tags)}. Either the sentences are "
        "stale or the tag should not be there."
    )


def test_the_scan_names_every_file_a_first_tag_would_make_stale() -> None:
    """The measurement the live check cannot make while nothing is tagged.

    With no tag, `_stale_claims` returns an empty list for the same reason a
    scan of an empty file list would, and a green run above is therefore not
    evidence that the scan works. Running it over this tree with a tag supplied
    is: it reads the real tracked files and reports what the first real tag will
    make false.

    The assertions are a floor, not a pinned inventory. Naming an exact set here
    would be a hand-maintained list gated on equality, which jams every branch
    that adds a document. What has to hold is that the scan reaches the tree,
    finds the sentence the README already pins, and finds it in **several
    files** — because "the fact is stated in more places than the rule is
    applied to" is the entire finding.

    The floor moved from two files to three when `CITATION.cff` joined the set.
    It had been stating this in a header comment the whole time and no entry in
    the vocabulary matched it, which is the sibling repository's exact defect —
    a comment explaining that `date-released` is absent, sitting above the field
    — reached here by a different road: not a wrong sentence, a right sentence
    nothing was watching.
    """
    _require_readable_tags()
    stale = _stale_claims(["v0.0.0-not-a-tag-in-this-repository"])
    files = {entry.split(":", 1)[0] for entry in stale}
    assert "README.md" in files, (
        "the scan does not reach README.md, whose sentence this repository already pins in "
        "both directions — so it is reading something other than the working tree"
    )
    assert len(files) > 2, (
        "the scan finds this claim in fewer files than the tree states it in. Either the "
        "documents that restate it have been corrected — in which case narrow this check and "
        f"say so — or the scan is no longer reading them. Files found: {sorted(files)}"
    )


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
