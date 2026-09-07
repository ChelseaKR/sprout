"""The offline precache list, checked against what the build actually wrote.

The rule this defends is the fourth hard one: offline by default. On the
published browser reference that rule rests entirely on a list of paths in
``service-worker.js``, and until now nothing compared that list to the build.

The tests below hold both directions, because they fail differently:

* an asset the build wrote and the list omits breaks that module offline, and
  only offline, so it survives every online test anyone runs;
* an asset the list names and the build did not write breaks *everything*,
  because ``cache.addAll()`` rejects atomically and the worker never installs
  -- and it, too, is invisible to anyone online.

The last group holds the property that makes the gate worth having: it cannot
pass over nothing. An absent worker, an unparseable list, an empty list, and an
unbuilt asset tree are each an error rather than agreement.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sprout.cli import app
from sprout.offline_shell import (
    OfflineShellError,
    check_offline_shell,
    required_entries,
    shell_entries,
)

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC = REPO_ROOT / "web-static" / "public"

WORKER_TEMPLATE = """\
const CACHE_NAME = "test-v1";
const SHELL = [
{entries}
];
self.addEventListener("install", () => {{}});
"""


def _worker(entries: list[str]) -> str:
    return WORKER_TEMPLATE.format(entries="\n".join(f'  "{entry}",' for entry in entries))


def _surface(root: Path, *, assets: list[str], data: list[str], shell: list[str]) -> Path:
    """A miniature built reference surface with a worker of our choosing."""
    root.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "app.js", "styles.css", "manifest.webmanifest"):
        (root / name).write_text("x", encoding="utf-8")
    for directory, names in (("assets", assets), ("data", data)):
        (root / directory).mkdir(exist_ok=True)
        for name in names:
            (root / directory / name).write_text("x", encoding="utf-8")
    (root / "service-worker.js").write_text(_worker(shell), encoding="utf-8")
    return root


def _complete_shell(assets: list[str], data: list[str]) -> list[str]:
    return (
        ["./", "./index.html", "./app.js", "./styles.css", "./manifest.webmanifest"]
        + [f"./assets/{name}" for name in assets]
        + [f"./data/{name}" for name in data]
    )


ASSETS = ["index.js", "answer.js", "topics.js"]
DATA = ["index.json", "config.json"]


def test_a_surface_whose_list_matches_the_build_has_no_problems(tmp_path: Path) -> None:
    root = _surface(
        tmp_path / "public", assets=ASSETS, data=DATA, shell=_complete_shell(ASSETS, DATA)
    )
    assert check_offline_shell(root) == []


def test_a_module_the_build_wrote_and_the_list_omits_is_reported(tmp_path: Path) -> None:
    """The live defect: topics.ts was added, the SHELL array was not."""
    shell = [entry for entry in _complete_shell(ASSETS, DATA) if entry != "./assets/topics.js"]
    root = _surface(tmp_path / "public", assets=ASSETS, data=DATA, shell=shell)

    problems = check_offline_shell(root)
    assert len(problems) == 1
    assert "./assets/topics.js" in problems[0]
    assert "the request fails" in problems[0]


def test_a_corpus_file_the_list_omits_is_reported(tmp_path: Path) -> None:
    """Not only modules. A missing bundle file is a page that cannot answer."""
    shell = [entry for entry in _complete_shell(ASSETS, DATA) if entry != "./data/index.json"]
    root = _surface(tmp_path / "public", assets=ASSETS, data=DATA, shell=shell)
    assert any("./data/index.json" in problem for problem in check_offline_shell(root))


@pytest.mark.parametrize("missing", ["index.html", "app.js", "styles.css", "manifest.webmanifest"])
def test_each_root_asset_is_required(tmp_path: Path, missing: str) -> None:
    shell = [entry for entry in _complete_shell(ASSETS, DATA) if entry != f"./{missing}"]
    root = _surface(tmp_path / "public", assets=ASSETS, data=DATA, shell=shell)
    assert any(missing in problem for problem in check_offline_shell(root))


def test_an_entry_the_build_did_not_write_is_reported_as_turning_offline_off(
    tmp_path: Path,
) -> None:
    """The asymmetric one. cache.addAll() rejects atomically.

    A single stale line does not degrade one asset; it stops the install
    handler resolving, so the worker never activates and nothing is cached at
    all. Everyone online sees a working page.
    """
    shell = [*_complete_shell(ASSETS, DATA), "./assets/deleted-last-month.js"]
    root = _surface(tmp_path / "public", assets=ASSETS, data=DATA, shell=shell)

    problems = check_offline_shell(root)
    assert len(problems) == 1
    assert "deleted-last-month.js" in problems[0]
    assert "atomically" in problems[0]


def test_the_scope_root_resolves_to_the_index_document(tmp_path: Path) -> None:
    """``./`` is not a file. It must not be reported as one the build missed."""
    root = _surface(
        tmp_path / "public", assets=ASSETS, data=DATA, shell=_complete_shell(ASSETS, DATA)
    )
    assert check_offline_shell(root) == []
    (root / "index.html").unlink()
    assert any(problem for problem in check_offline_shell(root))


def test_a_duplicated_entry_is_reported(tmp_path: Path) -> None:
    shell = [*_complete_shell(ASSETS, DATA), "./assets/index.js"]
    root = _surface(tmp_path / "public", assets=ASSETS, data=DATA, shell=shell)
    assert any("more than once" in problem for problem in check_offline_shell(root))


# ---------------------------------------------------------------------------
# The gate cannot pass over nothing.


def test_an_absent_worker_is_an_error_not_an_agreement(tmp_path: Path) -> None:
    root = _surface(
        tmp_path / "public", assets=ASSETS, data=DATA, shell=_complete_shell(ASSETS, DATA)
    )
    (root / "service-worker.js").unlink()
    with pytest.raises(OfflineShellError, match="no service worker"):
        check_offline_shell(root)


def test_an_unparseable_shell_is_an_error(tmp_path: Path) -> None:
    root = _surface(
        tmp_path / "public", assets=ASSETS, data=DATA, shell=_complete_shell(ASSETS, DATA)
    )
    (root / "service-worker.js").write_text("const CACHE = 'v1';\n", encoding="utf-8")
    with pytest.raises(OfflineShellError, match="could not be read"):
        check_offline_shell(root)


def test_an_empty_shell_is_an_error_rather_than_a_vacuous_pass(tmp_path: Path) -> None:
    """`required - set()` is everything, but an empty list must not even get there."""
    root = _surface(tmp_path / "public", assets=ASSETS, data=DATA, shell=[])
    with pytest.raises(OfflineShellError, match="empty SHELL"):
        check_offline_shell(root)


@pytest.mark.parametrize("directory", ["assets", "data"])
def test_an_unbuilt_asset_tree_is_an_error(tmp_path: Path, directory: str) -> None:
    """Without this, running the gate before the build would report success."""
    root = _surface(
        tmp_path / "public", assets=ASSETS, data=DATA, shell=_complete_shell(ASSETS, DATA)
    )
    for path in (root / directory).iterdir():
        path.unlink()
    with pytest.raises(OfflineShellError, match="never built"):
        required_entries(root)
    (root / directory).rmdir()
    with pytest.raises(OfflineShellError, match="does not exist"):
        check_offline_shell(root)


def test_shell_entries_reads_the_committed_worker() -> None:
    """The parser must work on the real file, not only on the template above."""
    worker = (PUBLIC / "service-worker.js").read_text(encoding="utf-8")
    entries = shell_entries(worker)
    assert "./assets/topics.js" in entries, (
        "the committed worker no longer precaches topics.js, which answer.ts imports"
    )
    assert "./data/index.json" in entries


def test_every_typescript_module_in_the_source_tree_is_precached() -> None:
    """The committed list, against the source the build compiles.

    ``make web-static-build`` runs ``sprout offline-check`` against the *built*
    tree, which is the authoritative comparison. This test is the one that runs
    in ``make test`` with no node toolchain: ``copy-site-assets.mjs`` copies
    every compiled ``dist/src/*.js``, and those come one-for-one from
    ``web-static/src/*.ts``, so the source tree predicts the asset list without
    building it.
    """
    sources = sorted(path.stem for path in (REPO_ROOT / "web-static" / "src").glob("*.ts"))
    assert sources, "web-static/src holds no TypeScript; this test would be vacuous"
    listed = set(shell_entries((PUBLIC / "service-worker.js").read_text(encoding="utf-8")))
    missing = [name for name in sources if f"./assets/{name}.js" not in listed]
    assert not missing, (
        f"web-static/src has {missing} but service-worker.js does not precache them; "
        "the page would request them over the network with the network off"
    )


# ---------------------------------------------------------------------------
# The CLI the Makefile calls.


def test_the_cli_reports_a_drifted_list_and_exits_one(tmp_path: Path) -> None:
    shell = [entry for entry in _complete_shell(ASSETS, DATA) if entry != "./assets/topics.js"]
    root = _surface(tmp_path / "public", assets=ASSETS, data=DATA, shell=shell)

    result = runner.invoke(app, ["offline-check", str(root)])
    assert result.exit_code == 1
    assert "topics.js" in result.output


def test_the_cli_exits_one_when_the_check_could_not_be_performed(tmp_path: Path) -> None:
    """An unreadable subject is not agreement.

    A gate that exits 0 because its input went missing has stopped gating, and
    the failure is invisible: the build stays green and the offline surface
    stops being checked.
    """
    root = _surface(
        tmp_path / "public", assets=ASSETS, data=DATA, shell=_complete_shell(ASSETS, DATA)
    )
    (root / "service-worker.js").unlink()

    result = runner.invoke(app, ["offline-check", str(root)])
    assert result.exit_code == 1
    assert "no service worker" in result.output


def test_the_cli_exits_two_when_pointed_at_no_directory(tmp_path: Path) -> None:
    result = runner.invoke(app, ["offline-check", str(tmp_path / "absent")])
    assert result.exit_code == 2


def test_the_cli_passes_on_the_committed_surface(tmp_path: Path) -> None:
    root = _surface(
        tmp_path / "public", assets=ASSETS, data=DATA, shell=_complete_shell(ASSETS, DATA)
    )
    result = runner.invoke(app, ["offline-check", str(root)])
    assert result.exit_code == 0
    assert "matches every asset this build wrote" in result.output
