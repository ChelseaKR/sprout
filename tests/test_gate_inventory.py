"""The gate-inventory doc test — FIX-02's "mechanical spine."

Re-parses ``docs/ROADMAP.md`` fresh on every run (no hand-maintained shadow list to drift)
and asserts every ``AUTO`` ledger row resolves to a real mechanism, and that the committed
``docs/audits/gate-inventory.md`` is the byte-identical output of regenerating it — the
same "committed artifact must match its generator" discipline the eval report and model
card already follow. A future ledger edit that claims AUTO for something nothing enforces
fails here, not silently.
"""

from __future__ import annotations

from pathlib import Path

from sprout.gate_inventory import (
    build_inventory,
    parse_ledger,
    render_markdown,
    unresolved_auto_rows,
)

_ROADMAP = Path("docs/ROADMAP.md")
_COMMITTED_INVENTORY = Path("docs/audits/gate-inventory.md")
_REPO_ROOT = Path(".")


def test_ledger_parses_a_nonzero_number_of_rows() -> None:
    rows = parse_ledger(_ROADMAP)
    assert len(rows) >= 20, (
        f"only parsed {len(rows)} ledger rows from {_ROADMAP} — the table-header regex "
        "likely stopped matching a section (e.g. a column header renamed); investigate "
        "before trusting a low count as 'clean'"
    )
    assert any(row.is_auto for row in rows), "expected at least one AUTO row in the ledger"


def test_every_auto_row_resolves_to_a_real_mechanism() -> None:
    resolutions = build_inventory(_ROADMAP, _REPO_ROOT)
    unresolved = unresolved_auto_rows(resolutions)
    assert not unresolved, "declared-but-unenforced AUTO row(s) (FIX-02):\n" + "\n".join(
        f"  - {r.row.section} / {r.row.metric}: {r.detail} (Measured by: {r.row.measured_by!r})"
        for r in unresolved
    )


def test_committed_gate_inventory_matches_regenerated_output() -> None:
    resolutions = build_inventory(_ROADMAP, _REPO_ROOT)
    regenerated = render_markdown(resolutions)
    assert _COMMITTED_INVENTORY.exists(), (
        f"{_COMMITTED_INVENTORY} is not committed — run `make gate-inventory` and commit it"
    )
    committed = _COMMITTED_INVENTORY.read_text(encoding="utf-8")
    assert committed == regenerated, (
        f"{_COMMITTED_INVENTORY} is stale — docs/ROADMAP.md changed since it was last "
        "regenerated; run `make gate-inventory` and commit the result"
    )
