"""Every install command this project's code prints or documents names the right package.

The distribution name and the import name are different here, and the difference is not
cosmetic: the bare import name on PyPI belongs to a stranger's library, so an install
command carrying it does not fail — it succeeds, quietly, against somebody else's code.
The README says so in bold. What it could not say is that the same command was still
sitting in module docstrings and in two runtime error messages, where nothing re-reads
prose and no reader ever looks.

Scope is deliberately **code**, not the whole tree, and the boundary is the finding
rather than a convenience:

* In `src/`, `tests/`, `scripts/`, `examples/` and `web-static/src/`, an install command
  is always an instruction. A docstring saying how to get the optional extra, and an
  exception message telling a user what to run next, are both read as commands and
  neither is re-read when the packaging changes.
* In Markdown the same string is often the opposite of an instruction. The README's own
  line is a prohibition — it names the wrong package precisely so a reader does not type
  it — and `CHANGELOG.md` quotes the retired wording on purpose, because a phrasing
  corrected out of the tree is still one the project wrote. A scan over prose would fire
  on both, which is the shape where a gate reddens on the paragraph explaining why it
  exists. Two dated ADRs illustrate packaging with the old name and were deliberately
  left as written for the same reason.

So this reads the files where the string can only ever be an instruction, and leaves the
files where a human re-reads it to the human. The declared name is read from
`pyproject.toml` rather than written here, so a rename moves this check with it and
nothing has to remember to.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE_INIT = ROOT / "src" / "sprout" / "__init__.py"

#: Where an install command is an instruction rather than a description of one. Prose
#: lives outside this on purpose — see the module docstring.
CODE_ROOTS = ("src/", "tests/", "scripts/", "examples/", "web-static/src/")

#: Suffixes whose text a reader or a user can be told something by.
CODE_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".js", ".mjs", ".sh", ".toml", ".cfg"})

#: `pip install X`, `pipx install X`, `uv pip install X`, `uv tool install X`, with any
#: flags in between and an optional quote and extras marker around the target. The
#: capture is the requirement token, so `sprout[corpus]` is one token and its base name
#: is what gets compared.
INSTALL_COMMAND = re.compile(
    r"(?:pipx|uv\s+pip|uv\s+tool|pip3?)\s+install\s+(?:-[\w-]+\s+)*['\"]?"
    r"([A-Za-z0-9._-]+(?:\[[A-Za-z0-9,._\- ]+\])?)"
)

#: The import name, which is also the CLI command, and is *not* the distribution. It is
#: written here rather than derived because the whole point is that the two differ; a
#: check that derived it from the distribution could not tell them apart.
IMPORT_NAME = "sprout"

#: A scan that has stopped finding the tree reports the same clean result as one that
#: read all of it, so the population is asserted rather than assumed.
MIN_CODE_FILES = 150

#: The one occurrence this change could not correct, named rather than quietly skipped.
#:
#: `src/sprout/providers/` is `TUNABLE_SURFACE`, and `tuning_scope._python_fingerprint`
#: builds its comparison from `ast.dump`, where a **docstring is a statement**. So a
#: correction confined to a module docstring — text nothing in `src/` reads, measured:
#: `__doc__` appears nowhere in the package — is indistinguishable to that gate from a
#: change to retrieval ranking, and it demands a `Tunes-Against:` trailer citing a
#: committed eval failure. There is no honest trailer for a comment, and writing a false
#: one to get past a gate is worse than the wrong sentence it would fix.
#:
#: This is an exemption, so it is self-limiting: `test_the_known_gap_is_still_a_gap`
#: fails the day the file is corrected or the gate learns to ignore docstrings, and the
#: entry has to be deleted then. It cannot outlive its reason quietly.
KNOWN_GAP = frozenset({"src/sprout/providers/__init__.py"})


def _git(*args: str) -> str | None:
    executable = shutil.which("git")
    if executable is None:  # pragma: no cover - git absent
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
    return done.stdout if done.returncode == 0 else None


def declared_distribution() -> str:
    """The name this project would publish under, read from the one file that owns it."""
    name = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["name"]
    assert isinstance(name, str) and name
    return name


def _tracked_code_files() -> list[Path]:
    listed = _git("ls-files", "-z")
    if listed is None:  # pragma: no cover - git unusable; the caller asserts the floor
        return []
    paths: list[Path] = []
    for name in listed.split("\0"):
        if not name or not name.startswith(CODE_ROOTS):
            continue
        path = ROOT / name
        if path.suffix in CODE_SUFFIXES and path.is_file():
            paths.append(path)
    return paths


def wrongly_named_installs(text: str, distribution: str) -> list[str]:
    """Install targets in this text that name a package this project does not publish.

    Only targets whose base name starts with the import name are reported. A command
    installing something else entirely — a requirements file, an editable path, a real
    third-party dependency — is not this check's business and reporting it would make
    the check a nuisance nobody keeps.
    """
    found: list[str] = []
    for match in INSTALL_COMMAND.finditer(text):
        target = match.group(1)
        base = target.split("[", 1)[0]
        if base.startswith(IMPORT_NAME) and base != distribution:
            found.append(target)
    return found


def test_no_install_command_in_code_names_a_package_this_project_does_not_publish() -> None:
    """The live half: an instruction that installs a stranger's library instead.

    Ten occurrences in seven files, two of them exception messages raised at runtime
    telling a user the exact command to run to get an optional extra — the loudest
    possible place to name the wrong package, and the only place in the repository
    nobody re-reads on the way past. Nine are corrected; the tenth is in `KNOWN_GAP`
    above with its reason and its expiry.
    """
    distribution = declared_distribution()
    files = _tracked_code_files()
    assert len(files) >= MIN_CODE_FILES, (
        f"only {len(files)} tracked code file(s) to read: this scan has stopped finding the "
        "tree, and a scan that reads nothing reports the same clean result as one that read "
        "everything"
    )
    problems: list[str] = []
    for path in files:
        if str(path.relative_to(ROOT)) in KNOWN_GAP:
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            for target in wrongly_named_installs(line, distribution):
                problems.append(f"{path.relative_to(ROOT)}:{line_number}: install {target}")
    assert not problems, (
        f"these install commands name a package this project does not publish under "
        f"({distribution!r} is what pyproject.toml declares):\n  " + "\n  ".join(problems) + "\n"
        "The bare import name on PyPI belongs to an unrelated library, so each of these "
        "succeeds against somebody else's code rather than failing."
    )


def test_the_known_gap_is_still_a_gap() -> None:
    """An exemption that has stopped exempting anything reads as coverage.

    Every entry above has to still contain the thing it is excused for. The day the
    docstring is corrected — or the day `tuning_scope` stops treating one as a behaviour
    change — this fails and the entry goes, rather than sitting in the tuple looking like
    a considered decision about a file nobody has looked at in a year.

    It also pins the count, because an exemption list is the one list where growth is the
    signal: a second entry means somebody widened an excuse instead of fixing a file.
    """
    distribution = declared_distribution()
    assert len(KNOWN_GAP) == 1, (
        f"the exemption list has grown to {sorted(KNOWN_GAP)}. Adding an entry here excuses a "
        "file from naming the right package; it is not a place to put a file that is merely "
        "inconvenient to fix."
    )
    for name in sorted(KNOWN_GAP):
        path = ROOT / name
        assert path.is_file(), f"{name} is exempted here and is not in the tree"
        assert wrongly_named_installs(path.read_text(encoding="utf-8"), distribution), (
            f"{name} is exempted from the scan above and no longer contains an install "
            "command naming the wrong package. Delete the entry — an exemption that exempts "
            "nothing is an exemption nobody can see the cost of."
        )


def test_the_package_derives_its_version_from_the_distribution_the_manifest_declares() -> None:
    """The rename's silent failure mode, made mechanical instead of remembered.

    `sprout.__init__` asks the installed metadata for a distribution *by name*. Given a
    name that is not installed it raises `PackageNotFoundError` and the module falls back
    to a labelled unknown — so a rename that moves the manifest and not this line
    publishes the sentinel as though it were a version, with nothing raised anywhere.

    Asserted against the source text rather than against the imported module, so it holds
    in a tree that has not been installed, which is the tree a rename is made in.
    """
    distribution = declared_distribution()
    source = PACKAGE_INIT.read_text(encoding="utf-8")
    named = re.findall(r"metadata\.version\(\s*[\"']([^\"']+)[\"']\s*\)", source)
    assert named, (
        f"{PACKAGE_INIT.relative_to(ROOT)} no longer resolves its version through "
        '`metadata.version("<distribution>")`, so this check has stopped reading the thing '
        "it is about rather than finding it correct"
    )
    wrong = sorted({name for name in named if name != distribution})
    assert not wrong, (
        f"{PACKAGE_INIT.relative_to(ROOT)} asks installed metadata for {wrong}, and "
        f"pyproject.toml declares {distribution!r}. That mismatch does not raise here: it "
        "raises PackageNotFoundError inside the module and publishes the not-installed "
        "sentinel as a version."
    )


@pytest.mark.parametrize(
    "command",
    [
        "pip install -e .",
        "pip install -r infra/requirements.txt",
        "uv pip install --python .venv-ext ragas==0.2.15",
        "uv pip install -e examples/herb-garden-plugin",
        "pipx install some-other-tool",
    ],
)
def test_the_scanner_leaves_alone_the_commands_that_are_not_about_this_package(
    command: str,
) -> None:
    """A check that fires on every install line is a check somebody deletes.

    These are all real commands from this repository. None of them names this project,
    and reporting them would make the scan above noise rather than a gate.
    """
    assert not wrongly_named_installs(command, declared_distribution())


def test_the_scanner_reports_a_wrong_name_and_accepts_the_declared_one() -> None:
    """The floor: the pattern still matches, and it discriminates.

    Both halves are needed. A pattern that stopped matching anything reports a clean
    scan, and a pattern that matches everything reports the declared name as wrong.

    The wrong-named control is **assembled rather than written**, and that is not
    fussiness: this file is inside the scanned roots, so a literal here would be a real
    finding about this file — the gate firing on the fixture that proves it works. The
    regex needs the target adjacent to the verb, so a concatenation is invisible to it
    while producing exactly the string at runtime.
    """
    distribution = declared_distribution()
    wrong = "pip install " + IMPORT_NAME + "[corpus]"
    assert wrongly_named_installs(wrong, distribution) == [f"{IMPORT_NAME}[corpus]"]
    assert wrongly_named_installs("pipx install " + IMPORT_NAME, distribution) == [IMPORT_NAME]
    assert not wrongly_named_installs(f"pipx install {distribution}", distribution)
    assert not wrongly_named_installs(f"pip install {distribution}[corpus]", distribution)
    assert distribution != IMPORT_NAME, (
        "the import name and the distribution name are the same, so this whole check is "
        "vacuous — every install command naming one names the other. If the collision on "
        "PyPI was resolved in this project's favour, delete this module and say so."
    )
