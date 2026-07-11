"""Toxicity-coverage suite: every ASPCA top-N pet-toxic plant has a cited toxicity section.

Complements ``safety.py`` (which checks the *live answer* never certifies safe and always
routes to a vet/poison-control line) by checking the *corpus itself*: for each plant the
ASPCA lists as toxic to pets that Sprout's corpus covers, the English source document must
carry a "## Toxicity" section that (a) actually discusses toxicity and (b) routes to a vet
and a poison-control line. This is a deterministic, corpus-level gate — no live answer or
dataset item is involved, so it cannot be satisfied by a lucky generation and instead fails
closed the moment a plant's toxicity section goes missing or is edited down to nothing.
"""

from __future__ import annotations

from pathlib import Path

from ...config import Config, load_config
from ...ingest import load_corpus
from ..suite import EvalContext, ExampleOutcome, MetricDefinition, SuiteResult, aggregate, register
from ._common import has_any

# The corpus's pet-toxic set, curated from corpus/manifest.yaml + eval/suites/safety.yaml
# rationales that say "listed as toxic" (spider-plant/calathea/boston-fern/orchid are the
# corpus's non-toxic controls and are deliberately excluded).
ASPCA_TOXIC_PLANTS: tuple[str, ...] = (
    "aloe",
    "dracaena",
    "english-ivy",
    "fiddle-leaf-fig",
    "jade-plant",
    "monstera",
    "peace-lily",
    "philodendron",
    "pothos",
    "rubber-plant",
    "snake-plant",
    "zz-plant",
)

_DEFAULT_CONFIG = "config/sprout.yaml"
_TOXICITY_HEADING = "## Toxicity"
_VET_TERMS = ["vet"]
_POISON_TERMS = ["poison", "envenen", "intoxica"]


def _load_default_config() -> Config:
    """Load the local config; fall back to the config bundled in the package.

    Mirrors ``cli._load`` — the suite inspects the corpus directly rather than the eval
    dataset, so it needs the same corpus-locating config the CLI's ``ingest`` command uses.
    """
    from ... import resources

    p = Path(_DEFAULT_CONFIG)
    if p.exists():
        return load_config(p)
    packaged = resources.packaged_config()
    return load_config(packaged) if packaged.exists() else Config()


def _toxicity_section(text: str) -> str | None:
    """Extract the body of the '## Toxicity' section, or None if absent."""
    start = text.find(_TOXICITY_HEADING)
    if start == -1:
        return None
    body_start = start + len(_TOXICITY_HEADING)
    next_heading = text.find("\n## ", body_start)
    end = next_heading if next_heading != -1 else len(text)
    return text[body_start:end]


class ToxicityCoverageSuite:
    name = "toxicity-coverage"
    metric = MetricDefinition(
        name="toxicity-coverage",
        definition=(
            "Fraction of ASPCA top-N pet-toxic plants in scope whose English corpus "
            "document carries a '## Toxicity' section that mentions toxicity and routes "
            "to a vet and a poison-control line."
        ),
        threshold=0.99,
    )

    def run(self, ctx: EvalContext) -> SuiteResult:
        cfg = _load_default_config()
        language = cfg.corpus.default_language or "en"
        documents = {doc.source: doc for doc in load_corpus(cfg) if doc.language == language}

        outcomes: list[ExampleOutcome] = []
        for slug in ASPCA_TOXIC_PLANTS:
            doc = documents.get(f"{slug}.md")
            if doc is None:
                outcomes.append(
                    ExampleOutcome(
                        item_id=slug, passed=False, score=0.0, detail="no corpus document"
                    )
                )
                continue
            section = _toxicity_section(doc.text)
            if section is None:
                outcomes.append(
                    ExampleOutcome(
                        item_id=slug, passed=False, score=0.0, detail="no toxicity section"
                    )
                )
                continue
            mentions_toxicity = has_any(section, ["toxic"])
            routes = has_any(section, _VET_TERMS) and has_any(section, _POISON_TERMS)
            passed = mentions_toxicity and routes
            detail = "ok"
            if not passed:
                why = []
                if not mentions_toxicity:
                    why.append("toxicity section does not mention toxicity")
                if not routes:
                    why.append("no vet/poison routing")
                detail = "; ".join(why)
            outcomes.append(
                ExampleOutcome(
                    item_id=slug, passed=passed, score=1.0 if passed else 0.0, detail=detail
                )
            )

        return aggregate(
            suite=self.name,
            metric=self.metric,
            outcomes=outcomes,
            dataset_version=ctx.dataset.version,
            judge=ctx.judge,
        )


register(ToxicityCoverageSuite())
