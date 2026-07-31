"""EXP-09: a machine-readable, per-row-cited toxicity table alongside prose.

Today toxicity is prose in each document's ``## Toxicity`` section — readable, but not
queryable. ``corpus/toxicity.yaml`` adds a species x animal x severity table, each row
carrying its own citation (``source_name``/``url``/``license``/``fetch_date``), so three
things become possible that prose alone cannot do:

1. **Deterministic coverage accounting** — :func:`coverage_report` names every
   species x animal pair the table covers, each with a citation, which is a stronger
   claim than the E1 eval slice (E1 only asserts *a* citation exists somewhere).
2. **Table-vs-prose consistency** — :func:`check_consistency` fails loudly if a row's
   ``toxic`` bool disagrees with what the corresponding document's prose actually says,
   per EXP-09's "dual-representation can drift -> the consistency check is mandatory"
   risk. It is scoped to the cat/dog phrasing the synthetic prose currently uses.
3. **A lossless import target** for real ASPCA-style data once the SME gate (R1) opens.

Rendered *answers* stay extractive from the cited prose (the never-certify-"safe" rule
lives in ``guards.py``/``config.py``, unchanged by this module); this table only selects
and routes. It never free-composes a sentence.

**Hard gate.** Every row in ``corpus/toxicity.yaml`` is ``synthetic: true`` and must stay
that way — original placeholder data, not a transcription of a real veterinary source —
until a veterinary toxicologist reviews this schema's semantics and every real row's
intended rendering (see the module docstring and header comment in the YAML file itself,
and ``docs/cards/data-card-corpus.md``). :func:`load_toxicity_table` raises if any row's
``url`` looks like a real (non ``example.invalid``) domain while still marked synthetic,
which would silently defeat the gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from . import resources
from .chunk import section_by_topic_slug
from .models import Document

# Cat/dog is what the synthetic prose corpus currently expresses per plant (one sentence
# covering both animals); check_consistency is scoped to those two until the prose does
# more. Other animals (e.g. "horse", "human") can still carry rows -- they are just not
# yet cross-checked against a matching prose sentence.
_CONSISTENCY_CHECKED_ANIMALS = frozenset({"cat", "dog"})

_NOT_APPLICABLE = "not_applicable"
_ALLOWED_SEVERITY_CLASSES = frozenset(
    {_NOT_APPLICABLE, "mild", "mild_moderate", "moderate", "severe"}
)


class ToxicityRow(BaseModel):
    """One species x animal toxicity fact, cited exactly like a manifest entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    species_slug: str
    species_name: str
    animal: str
    toxic: bool
    principle: str
    severity_class: str
    source_name: str
    url: str
    license: str
    fetch_date: str
    synthetic: bool = True

    @model_validator(mode="after")
    def _check_invariants(self) -> ToxicityRow:
        if self.severity_class not in _ALLOWED_SEVERITY_CLASSES:
            raise ValueError(
                f"{self.species_slug}/{self.animal}: severity_class "
                f"{self.severity_class!r} is not in {sorted(_ALLOWED_SEVERITY_CLASSES)} "
                "(new values need SME sign-off per EXP-09 before this loader accepts them)"
            )
        if self.toxic and self.severity_class == _NOT_APPLICABLE:
            raise ValueError(
                f"{self.species_slug}/{self.animal}: toxic=true rows must carry a real "
                f"severity_class, not {_NOT_APPLICABLE!r}"
            )
        if not self.toxic and self.severity_class != _NOT_APPLICABLE:
            raise ValueError(
                f"{self.species_slug}/{self.animal}: toxic=false rows must use "
                f"severity_class={_NOT_APPLICABLE!r}, got {self.severity_class!r}"
            )
        if not self.principle.strip():
            raise ValueError(f"{self.species_slug}/{self.animal}: principle must not be empty")
        if not self.synthetic and "example.invalid" in self.url:
            raise ValueError(
                f"{self.species_slug}/{self.animal}: marked non-synthetic but url still "
                "points at the placeholder example.invalid domain"
            )
        if self.synthetic and "example.invalid" not in self.url and self.url:
            # A synthetic row pointing at a real-looking domain would silently defeat the
            # SME hard gate (EXP-09): real rows must flip `synthetic` to false explicitly.
            raise ValueError(
                f"{self.species_slug}/{self.animal}: synthetic=true row has a non-placeholder "
                f"url ({self.url!r}) -- flip synthetic to false only after SME sign-off"
            )
        return self


def load_toxicity_table(path: str | Path) -> list[ToxicityRow]:
    """Load and validate ``corpus/toxicity.yaml``. Missing/empty file raises loudly.

    Mirrors the manifest-discipline pattern in ``ingest.load_manifest``: every row is
    schema-validated and every citation field required, so a malformed or under-cited row
    fails at load time rather than reaching a coverage report or a routing decision.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"toxicity table not found: {p}")
    raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    rows = (raw or {}).get("rows")
    if not rows:
        raise ValueError(f"toxicity table {p} has no 'rows' list")
    return [ToxicityRow.model_validate(row) for row in rows]


def load_configured_toxicity_table(table_path: str) -> list[ToxicityRow]:
    """Load the toxicity table from a config-relative path, honoring the packaged fallback."""
    return load_toxicity_table(resources.locate(table_path))


def coverage_report(rows: list[ToxicityRow]) -> dict[str, dict[str, ToxicityRow]]:
    """Species -> animal -> the row covering that pair, each still carrying its citation.

    This is the "coverage report can name every species x animal pair the corpus covers,
    with a citation per cell" excellence bar from EXP-09. Later rows for the same
    (species, animal) pair overwrite earlier ones, matching the manifest's file-keyed
    last-write-wins convention.
    """
    report: dict[str, dict[str, ToxicityRow]] = {}
    for row in rows:
        report.setdefault(row.species_slug, {})[row.animal] = row
    return report


def species_animal_pairs(rows: list[ToxicityRow]) -> set[tuple[str, str]]:
    """The set of (species_slug, animal) pairs the table covers."""
    return {(row.species_slug, row.animal) for row in rows}


_NOT_LISTED_PHRASE = "does not list"


def check_consistency(rows: list[ToxicityRow], documents: list[Document]) -> list[str]:
    """Fail loudly if a cat/dog row disagrees with its document's prose.

    Each English document's ``## Toxicity`` section states, in one sentence, either "the
    cited reference lists <plant> as toxic to cats and dogs" or "the cited reference does
    not list <plant> as toxic to cats or dogs" (see ``corpus/processed/*.md``). This
    deterministically checks that pattern against ``row.toxic`` for every cat/dog row, so
    a table edit that drifts from the prose (or vice versa) is caught instead of silently
    shipping two disagreeing answers to the same question -- the "table-vs-prose
    consistency check is mandatory, not optional" requirement from EXP-09.

    Returns a list of human-readable contradiction descriptions; empty means consistent.
    """
    sections_by_slug: dict[str, str] = {}
    for doc in documents:
        if doc.language != "en":
            continue
        slug = Path(doc.source).name.removesuffix(".md")
        body = section_by_topic_slug(doc.text, doc.topic, "toxicity")
        if body is not None:
            sections_by_slug[slug] = body

    problems: list[str] = []
    for row in rows:
        if row.animal not in _CONSISTENCY_CHECKED_ANIMALS:
            continue
        body = sections_by_slug.get(row.species_slug)
        if body is None:
            problems.append(
                f"{row.species_slug}/{row.animal}: table row has no matching English "
                "document with a Toxicity section to check against"
            )
            continue
        not_listed = _NOT_LISTED_PHRASE in body
        if not_listed == row.toxic:
            prose_says = "does not list it as toxic" if not_listed else "lists it as toxic"
            problems.append(
                f"{row.species_slug}/{row.animal}: table says toxic={row.toxic} but the "
                f"corpus prose {prose_says} to cats/dogs -- table and prose disagree"
            )
    return problems
