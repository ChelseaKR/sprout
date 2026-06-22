"""The eval dataset model and loader — fail-closed at the data boundary.

Cases are authored in YAML (one file per suite under ``eval/suites/``) and parsed into a
single Pydantic ``DatasetItem`` model with ``extra='forbid'``, so a mistyped field fails
the load rather than silently doing nothing. The combined dataset is content-addressed:
its version is ``sha256:<hash[:12]>`` over the canonical items, and a committed
``eval/suites.sha256`` sidecar pins it — a mismatch raises (tamper-evident, reproducible).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from ..determinism import sha256_of_obj, short

ExpectedBehavior = Literal["answer", "partial", "refuse-and-redirect"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provenance(_Strict):
    """Required on every case: where the (synthetic) case content came from."""

    source: str
    license: str
    added: str  # ISO-8601 date the case was added
    note: str = ""


class TargetResponse(_Strict):
    """A recorded assistant answer, replayed by the scripted offline adapter."""

    text: str
    citations: list[str] = []
    refused: bool = False
    confidence: float | None = None
    language: str | None = None
    safety_notice: str | None = None


class DatasetItem(_Strict):
    """One evaluation case. A case participates in a suite only if it has that suite's
    required fields (e.g. groundedness needs ``sources``); a selected suite with no
    applicable items fails closed in the runner."""

    schema_version: str = "1.0"
    id: str
    question: str
    provenance: Provenance
    language: str | None = None
    expected_behavior: ExpectedBehavior | None = None
    rationale: str = ""

    target_response: TargetResponse | None = None

    # groundedness / accuracy
    sources: list[str] = []
    expected_facts: list[str] = []

    # refusal / safety
    should_refuse: bool | None = None
    attack: str | None = None
    is_toxicity_query: bool = False
    forbidden_terms: list[str] = []
    must_mention: list[str] = []

    # calibration
    confidence: float | None = None
    is_correct: bool | None = None

    # multilingual
    pair_id: str | None = None
    is_reference: bool = False


class Dataset(BaseModel):
    """A content-addressed collection of cases."""

    model_config = ConfigDict(frozen=True)

    version: str
    content_hash: str
    items: tuple[DatasetItem, ...]

    @model_validator(mode="after")
    def _non_empty(self) -> Dataset:
        if not self.items:
            raise ValueError("dataset is empty")
        return self

    @classmethod
    def from_items(cls, items: list[DatasetItem]) -> Dataset:
        ids = [it.id for it in items]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate case ids: {dupes}")
        canonical = sorted((it.model_dump() for it in items), key=lambda d: d["id"])
        content_hash = sha256_of_obj(canonical)
        return cls(
            version=f"sha256:{short(content_hash)}", content_hash=content_hash, items=tuple(items)
        )

    def by_id(self, item_id: str) -> DatasetItem:
        for it in self.items:
            if it.id == item_id:
                return it
        raise KeyError(item_id)  # pragma: no cover - defensive


class DatasetError(ValueError):
    """Raised on a malformed dataset or a hash-sidecar mismatch (fail closed)."""


def _coerce_cases(raw: Any, path: Path) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and "cases" in raw:
        cases = raw["cases"]
    elif isinstance(raw, list):
        cases = raw
    else:
        raise DatasetError(f"{path}: expected a list or a mapping with a 'cases' key")
    if not isinstance(cases, list):
        raise DatasetError(f"{path}: 'cases' must be a list")
    return cases


def load_cases(path: str | Path) -> list[DatasetItem]:
    """Parse one YAML suite file into validated cases."""
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    out: list[DatasetItem] = []
    for entry in _coerce_cases(raw, p):
        try:
            out.append(DatasetItem.model_validate(entry))
        except Exception as exc:
            raise DatasetError(f"{p}: invalid case {entry.get('id', '?')!r}: {exc}") from exc
    return out


def load_suite_dir(
    directory: str | Path, *, verify_hash: bool = True, sidecar: str | Path | None = None
) -> Dataset:
    """Load and combine every ``*.yaml`` suite file under ``directory`` into one Dataset.

    If a sidecar hash file exists (default ``<directory>/../suites.sha256``) and
    ``verify_hash`` is set, the loaded content hash must match it or the load fails closed.
    """
    d = Path(directory)
    files = sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml"))
    if not files:
        raise DatasetError(f"no suite YAML files under {d}")
    items: list[DatasetItem] = []
    for f in files:
        items.extend(load_cases(f))
    dataset = Dataset.from_items(items)

    sidecar_path = Path(sidecar) if sidecar else d.parent / "suites.sha256"
    if verify_hash:
        # A missing pin is a hard failure, not a silent skip — otherwise deleting the
        # sidecar would disable tamper-evidence (fail closed at the integrity boundary).
        if not sidecar_path.exists():
            raise DatasetError(
                f"integrity sidecar {sidecar_path} is missing; refusing to load unverified. "
                f"Regenerate it (e.g. via `sprout eval --update-baseline`)."
            )
        expected = sidecar_path.read_text(encoding="utf-8").strip().split()[0]
        if expected != dataset.content_hash:
            raise DatasetError(
                f"dataset hash mismatch: sidecar {expected[:12]} != computed "
                f"{dataset.content_hash[:12]} (cases changed; regenerate {sidecar_path.name})"
            )
    return dataset


def write_sidecar(dataset: Dataset, sidecar: str | Path) -> None:
    """Write the dataset content hash to its sidecar file."""
    Path(sidecar).write_text(dataset.content_hash + "\n", encoding="utf-8")
