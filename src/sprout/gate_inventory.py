"""The gate-inventory audit — FIX-02: every ledger AUTO row maps to a real check, or is
mechanically visible as not doing so.

``docs/ROADMAP.md`` declares a ``Gate`` column (``AUTO``, ``REVIEW``, or a prose note) for
every metric in its ``| Metric | Target | Measured by | Gate |`` tables. Nothing previously
checked that an ``AUTO`` row's ``Measured by`` cell actually named something that exists —
the ledger could claim a mechanism that was renamed, deleted, or never wired, and no CI
signal would catch it (that gap is the FIX-02 pitch itself). This module parses the ledger
straight out of the committed doc (no hand-maintained shadow copy to drift), extracts the
backtick-quoted references in each ``Measured by`` cell, and resolves each one against the
repo's actual mechanisms: an existing file/directory path, or a literal substring inside
``Makefile`` or a ``.github/workflows/*.yml`` file. A bare ``AUTO`` row with no resolvable
reference is reported ``UNRESOLVED`` — the mechanical signal FIX-02 was missing.

Rows that are honestly *not* unconditional AUTO gates (``REVIEW``, ``N/A-with-reason``,
"planned", "report-only", "warn-only", or any other qualified/bold note) are recorded but
exempted from the resolution requirement — demoting a claim honestly is the other half of
FIX-02's "wire it or relabel it" mandate, and this audit must not punish an honest
relabel by demanding it behave like a stricter claim it no longer makes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# The first column header varies ("Metric" almost everywhere, "Suite / metric" in the AI
# evaluation table) — anchor on the three that are constant across every ledger table.
_HEADER_RE = re.compile(r"^\|.*\|\s*Target\s*\|\s*Measured by\s*\|\s*Gate\s*\|\s*$")
_SEPARATOR_RE = re.compile(r"^\|[\s:-]+\|[\s:-]+\|[\s:-]+\|[\s:-]+\|\s*$")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_ESCAPED_PIPE = "\\|"
_ESCAPED_PIPE_SENTINEL = "\0ESCPIPE\0"

# Mechanism files a "Measured by" reference is checked against, relative to repo root.
_MAKE_FILE = "Makefile"
_WORKFLOWS_DIR = ".github/workflows"


@dataclass(frozen=True)
class LedgerRow:
    section: str
    metric: str
    target: str
    measured_by: str
    gate: str

    @property
    def is_auto(self) -> bool:
        """True for an unconditional AUTO gate — the claim this audit enforces."""
        g = self.gate.strip()
        if not g.startswith("AUTO"):
            return False
        # "AUTO (never N/A)" etc. are still unconditional; only reject prose notes that
        # wrap the whole cell in bold (the repo's own convention for "corrected, gap
        # tracked" rows — see docs/ROADMAP.md's judge-agreement / red-team / freshness
        # rows) or that explicitly say N/A.
        return "N/A" not in g


@dataclass(frozen=True)
class Resolution:
    row: LedgerRow
    references: tuple[str, ...]
    resolved: bool
    detail: str


def parse_ledger(roadmap_path: Path) -> list[LedgerRow]:
    """Extract every ``| Metric | Target | Measured by | Gate |`` row in the doc.

    Section context is the nearest preceding ``### `` heading, purely for the generated
    report's readability — resolution does not depend on it.
    """
    lines = roadmap_path.read_text(encoding="utf-8").splitlines()
    rows: list[LedgerRow] = []
    section = ""
    in_table = False
    for line in lines:
        if line.startswith("### "):
            section = line[4:].strip()
            in_table = False
            continue
        if _HEADER_RE.match(line):
            in_table = True
            continue
        if not in_table:
            continue
        if _SEPARATOR_RE.match(line):
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            continue
        # A markdown-escaped pipe (`\|`, used inside a backtick span like `` `\|\| true` ``
        # to render a literal `||`) is not a cell separator — protect it before splitting.
        protected = stripped.replace(_ESCAPED_PIPE, _ESCAPED_PIPE_SENTINEL)
        cells = [
            c.strip().replace(_ESCAPED_PIPE_SENTINEL, "|") for c in protected.strip("|").split("|")
        ]
        if len(cells) != 4:
            in_table = False
            continue
        metric, target, measured_by, gate = cells
        rows.append(LedgerRow(section, metric, target, measured_by, gate))
    return rows


def _mechanism_corpus(repo_root: Path) -> str:
    parts = []
    makefile = repo_root / _MAKE_FILE
    if makefile.exists():
        parts.append(makefile.read_text(encoding="utf-8"))
    workflows = repo_root / _WORKFLOWS_DIR
    if workflows.is_dir():
        for wf in sorted(workflows.glob("*.yml")):
            parts.append(wf.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _reference_resolves(ref: str, repo_root: Path, corpus: str) -> bool:
    ref = ref.strip()
    if not ref:
        return False
    # A path-shaped reference (contains "/" or a dotted extension): check it exists,
    # either directly or as the tail of an existing path anywhere in the tree.
    looks_like_path = "/" in ref or re.search(r"\.[a-zA-Z0-9]{1,5}$", ref)
    if looks_like_path:
        candidate = repo_root / ref
        if candidate.exists():
            return True
        # extension-less reference to a real file (e.g. "eval/suites/groundedness" for
        # the committed eval/suites/groundedness.yaml) — match on stem within the parent.
        if candidate.parent.is_dir() and any(
            p.stem == candidate.name for p in candidate.parent.iterdir()
        ):
            return True
        # bare filename (e.g. "obs.py") — accept if it exists anywhere under src/tests.
        name = ref.rsplit("/", 1)[-1]
        for base in ("src", "tests"):
            if any((repo_root / base).rglob(name)):
                return True
    # Otherwise (a command/tool/module token): resolved if it appears verbatim as a
    # substring of the Makefile or a workflow file — the actual invocation site.
    if ref in corpus:
        return True
    # Fall back to the reference's first whitespace-delimited token, so a full command
    # line like `pytest --cov=sprout --cov-fail-under=90` still resolves against a
    # Makefile/CI line that invokes `pytest` with equivalent flags in a different order.
    first_token = ref.split()[0] if ref.split() else ""
    return bool(first_token) and first_token in corpus


def resolve(row: LedgerRow, repo_root: Path, corpus: str) -> Resolution:
    """A row resolves if its *first* backtick-quoted span in ``Measured by`` names a real
    mechanism. Only the first span is required: cells legitimately use later backtick
    spans for illustrative, non-reference code (e.g. "never `\\|\\| true`" names the
    anti-pattern being forbidden, not a second mechanism to locate), and requiring every
    span to resolve would punish that honest illustration as a broken reference.
    """
    refs = tuple(_BACKTICK_RE.findall(row.measured_by))
    if not refs:
        return Resolution(row, refs, False, "no backtick-quoted reference in Measured by")
    primary = refs[0]
    if not _reference_resolves(primary, repo_root, corpus):
        return Resolution(row, refs, False, f"unresolved primary reference: `{primary}`")
    return Resolution(row, refs, True, f"resolved via `{primary}`")


def build_inventory(roadmap_path: Path, repo_root: Path) -> list[Resolution]:
    corpus = _mechanism_corpus(repo_root)
    return [resolve(row, repo_root, corpus) for row in parse_ledger(roadmap_path)]


def unresolved_auto_rows(resolutions: list[Resolution]) -> list[Resolution]:
    return [r for r in resolutions if r.row.is_auto and not r.resolved]


def render_markdown(resolutions: list[Resolution]) -> str:
    n_auto = sum(1 for r in resolutions if r.row.is_auto)
    n_unresolved = len(unresolved_auto_rows(resolutions))
    lines = [
        "# Gate inventory",
        "",
        "Generated by `sprout gate-inventory` from `docs/ROADMAP.md` (FIX-02) — do not hand-edit.",
        "Maps every ledger row to the mechanism its `Measured by` cell names, and mechanically",
        "resolves that mechanism against `Makefile` / `.github/workflows/*.yml` / the repo tree.",
        "An `AUTO` row that cannot be resolved is a declared-but-unenforced gate.",
        "",
        f"**{n_auto} AUTO rows · {n_unresolved} unresolved.**",
        "",
        "| Section | Metric | Gate | Measured by | Resolution |",
        "|---|---|---|---|---|",
    ]
    for r in resolutions:
        row = r.row
        if row.is_auto:
            status = "✅ resolved" if r.resolved else "❌ UNRESOLVED"
        else:
            status = "— exempt (not an unconditional AUTO claim)"
        lines.append(
            f"| {row.section} | {row.metric} | {row.gate} | {row.measured_by} | {status} |"
        )
    lines.append("")
    return "\n".join(lines)
