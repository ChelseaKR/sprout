"""SME corpus-contribution workflow: propose a cited passage **and** an eval case (E5).

``docs/RESEARCH-ROADMAP.md`` E5 asks for "a low-/no-code 'propose a cited passage + an
eval case' path with provenance fields (source, license, fetch_date, lang, topic)
enforced and a representational-harm checklist". `USER-RESEARCH.md`'s panel converges on
the corpus as *the* bottleneck (personas B2 "extension SME" and E1 "owner/maintainer"),
and EV1/EV4 are the evidence that unsourced plant-care text is exactly what goes wrong
in this domain. EXP-12 (``corpus_report.py``) built the **maintainer-side** QA layer for
corpus growth; this is its **contributor-side** counterpart, and it deliberately reuses
that module rather than re-implementing its rules.

A proposal is one self-contained YAML file (see :data:`TEMPLATE`, emitted by
``sprout propose template``). The ``corpus_proposal`` GitHub issue form is the same path
for a contributor who never touches YAML or Python: it collects the parts only the
contributor can supply — species, source, license, fetch date, the passages, the eval
question and the phrase it must contain, and the harm checklist — which a maintainer then
transcribes into a proposal file, filling in the mechanical remainder (schema version,
submitter/date attribution, section titles, eval-case id/sources/provenance). It is a
subset of the schema by design, not a field-for-field mirror of it.

``sprout propose check`` reviews a proposal **offline and deterministically** and emits
one of three statuses:

``changes-requested``
    At least one ``error`` finding. The proposal is not mergeable as authored.
``ready-for-expert-review``
    Mechanically clean, but the content is safety-bearing (toxicity/ingestion prose, or
    a toxicity eval case) and carries no committed expert sign-off. This is the honest
    encoding of a gate the repo already declares in prose — ``RESEARCH-ROADMAP.md``
    ("Safety path requires expert sign-off, not synthetic consensus") and
    ``corpus/toxicity.yaml``'s ``synthetic: true`` hard gate — as a machine-checked
    state rather than tribal knowledge. It is *not* an error: the tool cannot conjure a
    veterinary toxicologist, and pretending otherwise would be the exact
    declared-but-unenforced defect FIX-02 exists to kill.
``ready-to-merge``
    Mechanically clean, and either not safety-bearing or carrying a committed
    ``expert_review`` sign-off artifact.

The representational-harm checklist is not box-ticking: every acknowledgement a machine
*can* falsify is cross-checked. ``no_medicinal_or_edibility_claims`` is checked against a
deterministic EN/ES claim vocabulary; the never-certify-"safe" rule is checked by running
the shipped :func:`sprout.guards.asserts_safety` over every proposed sentence, so a
passage that certifies a plant safe cannot enter the corpus through this door any more
than it can leave through the answer path.

Nothing here writes to ``corpus/``: review is a pure function of the proposal plus the
corpus already on disk. Merging an accepted proposal stays a human, reviewed act.

The gate is **discovery-based**, not example-based. ``sprout propose check`` with no
arguments — the form ``make propose-check`` and the CI step use — walks the repository and
reviews every file that *has the shape of a proposal*, wherever it was filed
(:func:`discover_proposals`). A proposal outside the declared submission locations
(:data:`PROPOSAL_DIRS`) is an **error**, not a silent skip, and discovering nothing at all
is a hard failure: a gate that reviews nothing is not a gate.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .chunk import slugify
from .config import Config
from .corpus_report import (
    canonical_topic_order,
    chunk_lint_issues,
    heading_slugs,
    mirror_parity_issues,
    plant_name_lint_issues,
    species_of,
)
from .determinism import sha256_of_text
from .freshness import check_freshness
from .guards import SAFETY_TOPIC_SLUGS, asserts_safety
from .ingest import ManifestEntry, load_corpus
from .models import Document
from .text import split_sentences, strip_accents

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .eval.dataset import DatasetItem

Severity = Literal["error", "warning"]
Status = Literal["changes-requested", "ready-for-expert-review", "ready-to-merge"]

#: Licenses a proposed passage may carry. Deliberately a short, redistributable-and-
#: attributable allowlist rather than a config knob: widening it is a licensing decision
#: with a paper trail (a commit here), not an operator's runtime toggle. Kept out of
#: ``config.py`` on purpose — that file is tuning-gated surface (``eval/tuning_scope.py``).
LICENSE_ALLOWLIST: tuple[str, ...] = (
    "CC0-1.0",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "CC-BY-3.0",
    "CC-BY-SA-3.0",
    "Apache-2.0",
    "public-domain",
)

#: The placeholder host every synthetic citation must use, matching the discipline
#: ``corpus/manifest.yaml`` and ``corpus/toxicity.yaml`` already follow: synthetic
#: content may never borrow a real domain's authority.
SYNTHETIC_HOST = "example.invalid"

#: Where a *submitted* proposal is expected to live, relative to the repo root — the
#: locations ``CONTRIBUTING.md``, the issue form, and :data:`TEMPLATE` all point a
#: contributor at. ``proposals/`` is where real submissions land; ``examples/corpus-
#: proposal`` holds the committed worked example. Discovery itself is repo-wide and
#: shape-based (:func:`discover_proposals`), so this tuple decides only whether a
#: proposal's *location* is acceptable — anything outside it is an error finding, never a
#: silent skip.
PROPOSAL_DIRS: tuple[str, ...] = ("proposals", "examples/corpus-proposal")

#: Where a committed expert sign-off artifact must live. Same reasoning as
#: :data:`LICENSE_ALLOWLIST`: the strongest gate in this module may only be discharged by
#: an artifact in the repo's audit trail, not by any path that happens to exist on disk.
EXPERT_REVIEW_ARTIFACT_DIRS: tuple[str, ...] = ("docs/audits",)

#: Directory names never descended into while discovering proposals: VCS metadata,
#: virtualenvs, caches, build output, vendored trees. Pruning is a speed measure only —
#: what makes a file a proposal is its shape, never its path.
_PRUNED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".eggs",
        ".git",
        ".hg",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".uv-cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
        "site",
        "venv",
    }
)

#: Distinctive top-level keys of the proposal schema. A YAML file carrying at least
#: :data:`_SIGNATURE_MIN` of them *is* a proposal for gate purposes — deliberately fewer
#: than the full set, so an incomplete submission is caught by the schema check rather
#: than waved through as "not a proposal".
_SIGNATURE_KEYS: frozenset[str] = frozenset(
    {"species", "documents", "provenance", "eval_case", "harm_checklist"}
)
_SIGNATURE_MIN = 3

#: Cheap textual pre-filter before parsing a candidate file — the one schema key no other
#: YAML in this repo uses. A file carrying it that then fails to parse is a *failure*, not
#: a skip (see :func:`_is_proposal_file`).
_SIGNATURE_MARKER = "harm_checklist"

#: Substrings that mark safety-bearing prose even outside a ``## Toxicity`` section.
#: Same vocabulary ``freshness.py`` uses to pick the stricter citation SLA.
_SAFETY_MARKERS = ("toxic", "toxico", "toxica", "toxicidad", "poison", "veneno", "ingest")

#: Medicinal / edibility claim vocabulary (EN + ES), matched on accent-stripped,
#: lower-cased word boundaries. A care corpus states care facts; "cures", "is edible",
#: or "medicinal" is a health claim Sprout has no standing to ground and no source
#: allowlisted here is authoritative for.
_CLAIM_RE = re.compile(
    r"\b("
    r"cure|cures|cured|curing|heal|heals|healed|remedy|remedies|medicinal|medicine|"
    r"edible|therapeutic|detox|detoxify|detoxifies|"
    r"cura|curan|curar|remedio|remedios|medicinal|medicinales|comestible|comestibles|"
    r"desintoxica|desintoxicante|terapeutico|terapeutica"
    r")\b|\bsafe to eat\b|\bseguro comer\b"
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProposalProvenance(_Strict):
    """Where the proposed passage came from — the manifest row it will become."""

    source_name: str
    url: str
    license: str
    fetch_date: str  # ISO-8601 date the snapshot was taken
    topic: str = "care"


class ProposalDocument(_Strict):
    """One language's full passage text, in the processed-corpus Markdown shape."""

    language: str
    title: str
    body: str


class HarmChecklist(_Strict):
    """The representational-harm checklist E5 asks for.

    Every acknowledgement must be ``true``. Where a machine can falsify one it does
    (see :func:`_claim_findings` and :func:`_safety_certification_findings`), so an
    affirmed box that the text contradicts fails the review rather than passing quietly.
    """

    reviewer: str
    reviewed_date: str
    common_names_regionally_neutral: bool
    no_medicinal_or_edibility_claims: bool
    traditional_knowledge_attributed: bool
    plain_language_reviewed: bool
    no_derogatory_or_stereotyped_framing: bool
    notes: str = ""

    def unchecked(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, value in sorted(self.__dict__.items())
            if isinstance(value, bool) and not value
        )


class ExpertReview(_Strict):
    """A committed clinical/horticultural sign-off for safety-bearing content."""

    reviewer: str
    credential: str
    reviewed_date: str
    scope: str
    artifact: str  # repo-relative path to the committed, dated sign-off


class Proposal(_Strict):
    """One SME corpus contribution: passages in every supported language + an eval case."""

    schema_version: int = 1
    species: str
    scientific_name: str
    submitter: str
    submitted_date: str
    synthetic: bool
    provenance: ProposalProvenance
    documents: tuple[ProposalDocument, ...]
    eval_case: dict[str, Any]
    harm_checklist: HarmChecklist
    expert_review: ExpertReview | None = None

    def document_for(self, language: str) -> ProposalDocument | None:
        for doc in self.documents:
            if doc.language == language:
                return doc
        return None

    def filename_for(self, language: str, reference_language: str) -> str:
        suffix = ".md" if language == reference_language else f".{language}.md"
        return f"{self.species}{suffix}"


class Finding(_Strict):
    """One review finding. ``code`` is stable and greppable; ``detail`` is for humans."""

    code: str
    severity: Severity
    detail: str


class ProposalReview(_Strict):
    """The full, deterministic review of one proposal file."""

    path: str
    species: str
    content_hash: str
    findings: tuple[Finding, ...]
    requires_expert_review: bool

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "warning")

    @property
    def status(self) -> Status:
        if self.errors:
            return "changes-requested"
        if self.requires_expert_review:
            return "ready-for-expert-review"
        return "ready-to-merge"


class ProposalError(ValueError):
    """Raised when a proposal file cannot be parsed at all (fail closed)."""


# --- loading -----------------------------------------------------------------------


def load_proposal(path: Path) -> Proposal:
    """Parse one proposal YAML file, failing closed on anything malformed."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - message shape only
        raise ProposalError(f"{path}: not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProposalError(f"{path}: expected a YAML mapping at the top level")
    try:
        return Proposal.model_validate(raw)
    except ValidationError as exc:
        raise ProposalError(f"{path}: {exc.error_count()} schema error(s): {exc}") from exc


def proposal_paths(targets: list[str]) -> list[Path]:
    """Expand CLI targets (files and/or directories) into a sorted list of YAML files."""
    paths: list[Path] = []
    for target in targets:
        p = Path(target)
        if p.is_dir():
            paths.extend(sorted(q for q in p.rglob("*.yaml") if q.is_file()))
        elif p.exists():
            paths.append(p)
        else:
            raise ProposalError(f"no such proposal file or directory: {p}")
    return paths


# --- discovery ---------------------------------------------------------------------
#
# The gate has to cover *a contributor's* proposal, not just the committed example, so
# discovery is by shape and repo-wide rather than by a hard-coded directory. Every step
# below fails closed: an unreadable proposal-shaped file raises, a proposal filed outside
# the declared locations is an error finding, and discovering nothing is a hard failure.


def _is_proposal_file(path: Path) -> bool:
    """Does this YAML file have the shape of a corpus proposal?

    Fails **closed**: a file whose text carries the proposal marker but which does not
    parse raises :class:`ProposalError` rather than being skipped, so a broken submission
    cannot drop out of the gate by being unreadable.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):  # pragma: no cover - unreadable file
        return False
    if _SIGNATURE_MARKER not in text:
        return False
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProposalError(
            f"{path}: reads as a corpus proposal ('{_SIGNATURE_MARKER}') but is not valid "
            f"YAML, so it cannot be reviewed: {exc}"
        ) from exc
    return isinstance(raw, dict) and len(_SIGNATURE_KEYS & set(raw)) >= _SIGNATURE_MIN


def discover_proposals(repo_root: Path) -> list[Path]:
    """Every corpus proposal committed anywhere under ``repo_root``, sorted.

    Location-independent on purpose. Whether a discovered proposal sits in one of
    :data:`PROPOSAL_DIRS` is then a *finding* (:func:`_location_findings`), so a misfiled
    proposal fails the gate loudly instead of never being looked at.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in _PRUNED_DIR_NAMES)
        for name in sorted(filenames):
            if not name.endswith((".yaml", ".yml")):
                continue
            path = Path(dirpath) / name
            if _is_proposal_file(path):
                found.append(path)
    return sorted(found)


def _repo_relative(path: Path, repo_root: Path) -> str | None:
    """``path`` as a repo-root-relative POSIX string, or ``None`` if it escapes the root."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def _in_declared_dirs(relative: str, declared: tuple[str, ...]) -> bool:
    return any(relative == d or relative.startswith(f"{d}/") for d in declared)


def _location_findings(path: Path, repo_root: Path) -> list[Finding]:
    """A proposal filed somewhere the workflow never names is ambiguous — fail closed."""
    relative = _repo_relative(path, repo_root)
    if relative is not None and _in_declared_dirs(relative, PROPOSAL_DIRS):
        return []
    return [
        Finding(
            code="proposal-location",
            severity="error",
            detail=(
                f"'{relative or path.as_posix()}' is a corpus proposal filed outside the "
                f"declared submission locations {list(PROPOSAL_DIRS)}; move it under "
                "'proposals/' so it is unambiguous which files the merge-blocking review "
                "covers"
            ),
        )
    ]


# --- individual checks -------------------------------------------------------------


def _identity_findings(proposal: Proposal, existing_species: frozenset[str]) -> list[Finding]:
    findings: list[Finding] = []
    if proposal.schema_version != 1:
        findings.append(
            Finding(
                code="schema-version",
                severity="error",
                detail=f"unsupported schema_version {proposal.schema_version} (this build reads 1)",
            )
        )
    if slugify(proposal.species) != proposal.species:
        findings.append(
            Finding(
                code="species-slug",
                severity="error",
                detail=(
                    f"species '{proposal.species}' is not a corpus slug "
                    f"(expected '{slugify(proposal.species)}')"
                ),
            )
        )
    if proposal.species in existing_species:
        findings.append(
            Finding(
                code="species-already-in-corpus",
                severity="error",
                detail=(
                    f"'{proposal.species}' already has corpus documents; propose an edit to the "
                    "existing files instead of a duplicate species"
                ),
            )
        )
    if not proposal.scientific_name.strip():
        findings.append(
            Finding(
                code="scientific-name-missing",
                severity="error",
                detail="scientific_name is required so a citation can be checked against a source",
            )
        )
    return findings


def _provenance_findings(proposal: Proposal, today: date) -> list[Finding]:
    findings: list[Finding] = []
    prov = proposal.provenance
    if prov.license not in LICENSE_ALLOWLIST:
        findings.append(
            Finding(
                code="license-not-allowlisted",
                severity="error",
                detail=(
                    f"license '{prov.license}' is not in the contribution allowlist "
                    f"{list(LICENSE_ALLOWLIST)}"
                ),
            )
        )
    if not prov.url.startswith(("http://", "https://")):
        findings.append(
            Finding(
                code="provenance-url",
                severity="error",
                detail=f"url '{prov.url}' is not an http(s) URL",
            )
        )
    # Host equality, not a substring test: `https://real.example.com/?q=example.invalid`
    # is a real host. Same predicate `freshness.check_liveness` uses to decide which
    # citations are placeholders.
    synthetic_host = (urlsplit(prov.url).hostname or "") == SYNTHETIC_HOST
    if proposal.synthetic and not synthetic_host:
        findings.append(
            Finding(
                code="synthetic-url-must-be-placeholder",
                severity="error",
                detail=(
                    f"synthetic: true, so the citation must use the {SYNTHETIC_HOST} placeholder "
                    f"host rather than borrow authority from '{prov.url}'"
                ),
            )
        )
    if not proposal.synthetic and synthetic_host:
        findings.append(
            Finding(
                code="real-url-must-not-be-placeholder",
                severity="error",
                detail=f"synthetic: false, but the citation points at the {SYNTHETIC_HOST} host",
            )
        )
    if not proposal.synthetic and proposal.expert_review is None:
        findings.append(
            Finding(
                code="real-content-needs-expert-review",
                severity="error",
                detail=(
                    "synthetic: false transcribes a real source into a safety-bearing corpus; "
                    "an `expert_review` block with a committed sign-off artifact is required "
                    "(same hard gate corpus/toxicity.yaml states for its rows)"
                ),
            )
        )
    findings.extend(_date_findings("submitted_date", proposal.submitted_date, today))
    findings.extend(
        _date_findings("harm_checklist.reviewed_date", proposal.harm_checklist.reviewed_date, today)
    )
    return findings


def _date_findings(field: str, value: str, today: date) -> list[Finding]:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return [
            Finding(
                code="date-unparseable",
                severity="error",
                detail=f"{field} {value!r} is not an ISO-8601 date (YYYY-MM-DD)",
            )
        ]
    if parsed > today:
        return [
            Finding(
                code="date-in-future",
                severity="error",
                detail=f"{field} {value} is in the future",
            )
        ]
    return []


def _freshness_findings(proposal: Proposal, config: Config, today: date) -> list[Finding]:
    """Reuse E7's citation-freshness check over the proposal's would-be manifest rows.

    An unparseable or future ``fetch_date`` is an error — freshness cannot even be
    evaluated. A merely *stale* citation is a warning: staleness of the corpus at large
    is the scheduled ``corpus-freshness`` workflow's job, and a hard failure here would
    turn every committed example proposal into a time bomb.

    Each row's ``topic`` is derived from the passage, not copied from
    ``provenance.topic``. ``freshness._is_toxicity`` only ever sees a manifest row's topic
    and title, so a proposal left on the template's default ``topic: care`` with a title
    like "Parlor palm care" would silently get the lax 365-day SLA even when the passage
    is nothing but toxicity prose. Safety-bearing prose is exactly what the stricter
    180-day SLA exists for, and it is the same predicate that decides whether the
    proposal needs an expert sign-off — so the two cannot drift apart.
    """
    reference = config.languages.supported[0] if config.languages.supported else "en"
    manifest = {
        proposal.filename_for(doc.language, reference): ManifestEntry(
            file=proposal.filename_for(doc.language, reference),
            title=doc.title,
            source_name=proposal.provenance.source_name,
            url=proposal.provenance.url,
            license=proposal.provenance.license,
            fetch_date=proposal.provenance.fetch_date,
            language=doc.language,
            topic="toxicity" if is_safety_bearing(doc.body) else proposal.provenance.topic,
        )
        for doc in proposal.documents
    }
    findings: list[Finding] = []
    for f in check_freshness(
        manifest,
        today=today,
        max_age_days=config.corpus.freshness.max_age_days,
        toxicity_max_age_days=config.corpus.freshness.toxicity_max_age_days,
    ):
        unusable = f.age_days is None or f.age_days < 0
        findings.append(
            Finding(
                code="fetch-date-unusable" if unusable else "citation-stale",
                severity="error" if unusable else "warning",
                detail=f"{f.file}: {f.reason}",
            )
        )
    return findings


def _language_findings(proposal: Proposal, config: Config) -> list[Finding]:
    supported = list(config.languages.supported)
    present = [doc.language for doc in proposal.documents]
    findings: list[Finding] = []
    for language in supported:
        if present.count(language) != 1:
            findings.append(
                Finding(
                    code="language-coverage",
                    severity="error",
                    detail=(
                        f"expected exactly one '{language}' document, found "
                        f"{present.count(language)}; every supported language "
                        f"{supported} must be proposed together (EN/ES parity is a merge gate)"
                    ),
                )
            )
    for language in present:
        if language not in supported:
            findings.append(
                Finding(
                    code="language-unsupported",
                    severity="error",
                    detail=f"language '{language}' is not in languages.supported {supported}",
                )
            )
    for doc in proposal.documents:
        if not doc.title.strip() or not doc.body.strip():
            findings.append(
                Finding(
                    code="document-empty",
                    severity="error",
                    detail=f"the '{doc.language}' document has an empty title or body",
                )
            )
    return findings


def _topic_findings(
    proposal: Proposal, target_topics: tuple[str, ...], reference: str
) -> list[Finding]:
    doc = proposal.document_for(reference)
    if doc is None or not target_topics:
        return []
    slugs = heading_slugs(doc.body)
    missing = [t for t in target_topics if t not in slugs]
    extra = [s for s in slugs if s not in target_topics]
    findings: list[Finding] = []
    if missing:
        findings.append(
            Finding(
                code="topic-coverage",
                severity="error",
                detail=(
                    f"the '{reference}' document is missing '## ' sections for {missing}; the "
                    f"corpus taxonomy is {list(target_topics)}"
                ),
            )
        )
    if extra:
        findings.append(
            Finding(
                code="topic-outside-taxonomy",
                severity="warning",
                detail=f"sections {extra} are outside the corpus taxonomy {list(target_topics)}",
            )
        )
    elif slugs != target_topics:
        findings.append(
            Finding(
                code="topic-order",
                severity="warning",
                detail=(
                    f"section order {list(slugs)} differs from the corpus canonical order "
                    f"{list(target_topics)}"
                ),
            )
        )
    return findings


def _as_documents(proposal: Proposal, config: Config) -> list[Document]:
    """Materialize the proposal's passages as in-memory corpus documents (never on disk)."""
    reference = config.languages.supported[0] if config.languages.supported else "en"
    documents: list[Document] = []
    for doc in proposal.documents:
        source = proposal.filename_for(doc.language, reference)
        documents.append(
            Document(
                doc_id=sha256_of_text(source)[:12],
                source=source,
                title=doc.title,
                language=doc.language,
                text=doc.body,
                source_name=proposal.provenance.source_name,
                url=proposal.provenance.url,
                license=proposal.provenance.license,
                fetch_date=proposal.provenance.fetch_date,
                topic=proposal.provenance.topic,
            )
        )
    return documents


def _corpus_lint_findings(
    proposal: Proposal, config: Config, documents: list[Document]
) -> list[Finding]:
    """Run EXP-12's shipped corpus lint over the proposed documents."""
    findings: list[Finding] = []
    by_language = {doc.language: doc for doc in documents}
    if "en" in by_language and "es" in by_language:
        for issue in mirror_parity_issues(proposal.species, by_language["en"], by_language["es"]):
            findings.append(
                Finding(code=f"parity-{issue.kind}", severity="error", detail=issue.detail)
            )
    if documents:
        for lint in chunk_lint_issues(config, documents):
            findings.append(
                Finding(code=f"lint-{lint.kind}", severity="error", detail=f"{lint.detail}")
            )
        for lint in plant_name_lint_issues(documents):
            findings.append(
                Finding(code=f"lint-{lint.kind}", severity="warning", detail=f"{lint.detail}")
            )
    return findings


def _sentences(documents: list[Document]) -> list[tuple[Document, str]]:
    pairs: list[tuple[Document, str]] = []
    for doc in documents:
        body = " ".join(line for line in doc.text.splitlines() if not line.startswith("#"))
        pairs.extend((doc, sentence) for sentence in split_sentences(body))
    return pairs


def _safety_certification_findings(config: Config, documents: list[Document]) -> list[Finding]:
    """The never-certify-"safe" rule, applied at the *contribution* boundary.

    The output guard already stops such a sentence from being rendered; running the same
    predicate here stops it from entering the corpus in the first place, so a proposal
    cannot smuggle in a certification the answer path would then have to refuse.
    """
    findings: list[Finding] = []
    for doc, sentence in _sentences(documents):
        if asserts_safety(sentence, doc.language, config.guards):
            findings.append(
                Finding(
                    code="safety-certification",
                    severity="error",
                    detail=(
                        f"{doc.source}: sentence certifies safety, which the corpus may never do "
                        f"— {sentence.strip()[:160]!r}"
                    ),
                )
            )
    return findings


def _claim_findings(proposal: Proposal, documents: list[Document]) -> list[Finding]:
    """Falsify the ``no_medicinal_or_edibility_claims`` acknowledgement where possible."""
    findings: list[Finding] = []
    for doc, sentence in _sentences(documents):
        match = _CLAIM_RE.search(strip_accents(sentence).lower())
        if match is None:
            continue
        affirmed = proposal.harm_checklist.no_medicinal_or_edibility_claims
        findings.append(
            Finding(
                code="medicinal-or-edibility-claim",
                severity="error",
                detail=(
                    f"{doc.source}: '{match.group(0)}' reads as a medicinal/edibility claim"
                    + (
                        " while harm_checklist.no_medicinal_or_edibility_claims is affirmed"
                        if affirmed
                        else ""
                    )
                    + f" — {sentence.strip()[:160]!r}"
                ),
            )
        )
    return findings


def _checklist_findings(proposal: Proposal) -> list[Finding]:
    findings: list[Finding] = []
    unchecked = proposal.harm_checklist.unchecked()
    if unchecked:
        findings.append(
            Finding(
                code="harm-checklist-unaffirmed",
                severity="error",
                detail=(
                    f"representational-harm checklist item(s) {list(unchecked)} are not affirmed; "
                    "resolve them in the text (and record what changed in `notes`) rather than "
                    "merging an acknowledged harm"
                ),
            )
        )
    if not proposal.harm_checklist.reviewer.strip():
        findings.append(
            Finding(
                code="harm-checklist-unattributed",
                severity="error",
                detail="harm_checklist.reviewer is required — a checklist needs an owner",
            )
        )
    return findings


def _expert_review_findings(proposal: Proposal, repo_root: Path, today: date) -> list[Finding]:
    review = proposal.expert_review
    if review is None:
        return []
    findings = _date_findings("expert_review.reviewed_date", review.reviewed_date, today)
    for field in ("reviewer", "credential", "scope"):
        if not str(getattr(review, field)).strip():
            findings.append(
                Finding(
                    code="expert-review-incomplete",
                    severity="error",
                    detail=f"expert_review.{field} is required",
                )
            )
    findings += _artifact_findings(proposal, review, repo_root)
    return findings


def _artifact_path_reason(raw: str, candidate: Path) -> str | None:
    """Why this ``expert_review.artifact`` path is not admissible, or ``None`` if it is."""
    if not raw:
        return "is empty"
    if candidate.is_absolute() or candidate.drive or raw.startswith("~"):
        return "must be a repo-relative path, not an absolute or home-relative one"
    if ".." in candidate.parts:
        return "must not traverse out of the repository with '..'"
    if candidate.suffix != ".md":
        return "must be a Markdown sign-off document (.md)"
    if not _in_declared_dirs(candidate.as_posix(), EXPERT_REVIEW_ARTIFACT_DIRS):
        return (
            "must live in the repository's audit trail — one of "
            f"{list(EXPERT_REVIEW_ARTIFACT_DIRS)}"
        )
    return None


def _artifact_findings(proposal: Proposal, review: ExpertReview, repo_root: Path) -> list[Finding]:
    """The sign-off artifact must be *contained*, *located*, and *about this proposal*.

    This is the strongest gate in the module — it is what turns
    ``ready-for-expert-review`` into ``ready-to-merge`` for safety-bearing content — so a
    bare ``exists()`` will not do: under that rule ``artifact: README.md`` discharges a
    veterinary toxicologist's sign-off. Three constraints instead:

    * **containment** — a repo-relative path under ``repo_root``, no absolute paths, no
      ``..`` traversal, and no symlink that resolves back out of the tree;
    * **location** — under :data:`EXPERT_REVIEW_ARTIFACT_DIRS`, the repo's audit trail,
      so a sign-off is reviewed and dated like every other committed audit;
    * **substance** — the file must actually name the species it signs off, the reviewer
      who signed it, and the date they signed it.
    """
    raw = review.artifact.strip()
    candidate = Path(raw)
    reason = _artifact_path_reason(raw, candidate)
    if reason is not None:
        return [
            Finding(
                code="expert-review-artifact-path",
                severity="error",
                detail=f"expert_review.artifact '{review.artifact}' {reason}",
            )
        ]

    resolved = repo_root / candidate
    contained = _repo_relative(resolved, repo_root) is not None
    if not contained:
        return [
            Finding(
                code="expert-review-artifact-path",
                severity="error",
                detail=(
                    f"expert_review.artifact '{review.artifact}' resolves outside the "
                    "repository (a symlink out of the tree is not a committed sign-off)"
                ),
            )
        ]
    if not resolved.is_file():
        return [
            Finding(
                code="expert-review-artifact-missing",
                severity="error",
                detail=(
                    f"expert_review.artifact '{review.artifact}' is not a committed file; the "
                    "sign-off must be a committed, dated artifact, not a claim in a YAML field"
                ),
            )
        ]

    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:  # pragma: no cover - message shape only
        return [
            Finding(
                code="expert-review-artifact-unsubstantiated",
                severity="error",
                detail=f"expert_review.artifact '{review.artifact}' is unreadable: {exc}",
            )
        ]
    folded = strip_accents(text).lower()
    missing = [
        label
        for label, needle in (
            (f"the species '{proposal.species}'", proposal.species),
            (f"the reviewer '{review.reviewer.strip()}'", review.reviewer.strip()),
            (f"the sign-off date {review.reviewed_date}", review.reviewed_date),
        )
        if not needle or strip_accents(needle).lower() not in folded
    ]
    if missing:
        return [
            Finding(
                code="expert-review-artifact-unsubstantiated",
                severity="error",
                detail=(
                    f"expert_review.artifact '{review.artifact}' does not mention "
                    f"{', '.join(missing)}; a sign-off must be an artifact about *this* "
                    "proposal, not any committed file that happens to exist"
                ),
            )
        ]
    return []


def _eval_case_findings(
    proposal: Proposal, config: Config, documents: list[Document], existing_ids: frozenset[str]
) -> list[Finding]:
    """The proposed eval case must load, be new, and actually exercise the new passage."""
    from .eval.dataset import DatasetItem

    try:
        item = DatasetItem.model_validate(proposal.eval_case)
    except ValidationError as exc:
        return [
            Finding(
                code="eval-case-schema",
                severity="error",
                detail=f"eval_case does not load as a DatasetItem: {exc.error_count()} error(s)",
            )
        ]
    findings: list[Finding] = []
    if item.id in existing_ids:
        findings.append(
            Finding(
                code="eval-case-id-taken",
                severity="error",
                detail=f"eval case id '{item.id}' already exists under eval/suites/",
            )
        )
    if item.language is not None and item.language not in config.languages.supported:
        findings.append(
            Finding(
                code="eval-case-language",
                severity="error",
                detail=f"eval case language '{item.language}' is not in languages.supported",
            )
        )
    sources = {doc.source for doc in documents}
    if not sources & set(item.sources):
        findings.append(
            Finding(
                code="eval-case-not-grounded-in-proposal",
                severity="error",
                detail=(
                    f"eval case sources {item.sources} name none of the proposed documents "
                    f"{sorted(sources)}; a proposal's case must exercise its own passage"
                ),
            )
        )
    findings.extend(_expected_fact_findings(item, documents))
    return findings


def _expected_fact_findings(item: DatasetItem, documents: list[Document]) -> list[Finding]:
    """Every ``expected_fact`` must literally appear in one of the proposed passages."""
    if not item.expected_facts:
        if item.should_refuse or item.expected_behavior == "refuse-and-redirect":
            return []
        return [
            Finding(
                code="eval-case-no-assertion",
                severity="error",
                detail=(
                    "eval case asserts nothing: give it `expected_facts` (what the answer must "
                    "contain) or mark it `should_refuse: true`"
                ),
            )
        ]
    haystacks = [strip_accents(doc.text).lower() for doc in documents]
    findings: list[Finding] = []
    for fact in item.expected_facts:
        needle = strip_accents(str(fact)).lower()
        if not any(needle in hay for hay in haystacks):
            findings.append(
                Finding(
                    code="expected-fact-unsupported",
                    severity="error",
                    detail=(
                        f"expected_fact {fact!r} does not appear in any proposed passage; the "
                        "case would assert something the corpus cannot ground"
                    ),
                )
            )
    return findings


def is_safety_bearing(text: str) -> bool:
    """Does this passage carry toxicity/ingestion prose?

    The single definition of "safety-bearing" in this module: it decides both which
    proposals are gated on an expert sign-off (:func:`requires_expert_review`) and which
    citations are held to the stricter toxicity freshness SLA
    (:func:`_freshness_findings`), so the two cannot answer differently.
    """
    if SAFETY_TOPIC_SLUGS & set(heading_slugs(text)):
        return True
    folded = strip_accents(text).lower()
    return any(marker in folded for marker in _SAFETY_MARKERS)


def requires_expert_review(proposal: Proposal, documents: list[Document]) -> bool:
    """Is this proposal safety-bearing, and therefore gated on a clinician/SME sign-off?"""
    if proposal.expert_review is not None:
        return False
    if any(is_safety_bearing(doc.text) for doc in documents):
        return True
    case = proposal.eval_case
    return bool(case.get("is_toxicity_query")) if isinstance(case, dict) else False


# --- the review --------------------------------------------------------------------


def review_proposal(
    proposal: Proposal,
    config: Config,
    *,
    today: date,
    existing_species: frozenset[str],
    existing_case_ids: frozenset[str],
    target_topics: tuple[str, ...],
    path: str = "<memory>",
    repo_root: Path = Path(),
    extra_findings: tuple[Finding, ...] = (),
) -> ProposalReview:
    """Review one proposal. A pure function of its arguments — no I/O beyond reading the
    ``expert_review.artifact`` sign-off, and no clock read.

    ``extra_findings`` carries findings the caller established about the file itself
    rather than its contents (today: where it was filed — see :func:`_location_findings`),
    so they are sorted and severity-counted with everything else.
    """
    reference = config.languages.supported[0] if config.languages.supported else "en"
    documents = _as_documents(proposal, config)
    findings: list[Finding] = list(extra_findings)
    findings += _identity_findings(proposal, existing_species)
    findings += _provenance_findings(proposal, today)
    findings += _freshness_findings(proposal, config, today)
    findings += _language_findings(proposal, config)
    findings += _topic_findings(proposal, target_topics, reference)
    findings += _corpus_lint_findings(proposal, config, documents)
    findings += _safety_certification_findings(config, documents)
    findings += _claim_findings(proposal, documents)
    findings += _checklist_findings(proposal)
    findings += _expert_review_findings(proposal, repo_root, today)
    findings += _eval_case_findings(proposal, config, documents, existing_case_ids)
    return ProposalReview(
        path=path,
        species=proposal.species,
        content_hash=sha256_of_text(proposal.model_dump_json())[:12],
        findings=tuple(sorted(findings, key=lambda f: (f.severity, f.code, f.detail))),
        requires_expert_review=requires_expert_review(proposal, documents),
    )


def corpus_context(config: Config) -> tuple[frozenset[str], tuple[str, ...]]:
    """The shipped corpus's species slugs and canonical topic taxonomy."""
    documents = load_corpus(config)
    species = frozenset(species_of(doc.source) for doc in documents)
    return species, canonical_topic_order(documents)


def existing_case_ids(suites_dir: Path) -> frozenset[str]:
    """Every eval case id already committed under ``eval/suites/`` (empty if absent)."""
    if not suites_dir.is_dir():
        return frozenset()
    ids: set[str] = set()
    for path in sorted(suites_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        cases = raw.get("cases", []) if isinstance(raw, dict) else raw
        for case in cases or []:
            if isinstance(case, dict) and isinstance(case.get("id"), str):
                ids.add(case["id"])
    return frozenset(ids)


def review_files(
    paths: list[Path],
    config: Config,
    *,
    today: date,
    suites_dir: Path = Path("eval/suites"),
    repo_root: Path = Path(),
    enforce_location: bool = False,
) -> list[ProposalReview]:
    """Load and review every proposal file, failing closed on an unparseable one.

    ``enforce_location`` additionally requires each file to sit in one of
    :data:`PROPOSAL_DIRS`. It is on for the discovery-driven gate (``make propose-check``
    / CI), where an unexpected location means the gate's coverage is ambiguous, and off
    when a human named the files explicitly — reviewing a draft in a scratch directory is
    not a defect.
    """
    species, target_topics = corpus_context(config)
    case_ids = existing_case_ids(suites_dir)
    reviews: list[ProposalReview] = []
    for path in paths:
        proposal = load_proposal(path)
        extra = tuple(_location_findings(path, repo_root)) if enforce_location else ()
        reviews.append(
            review_proposal(
                proposal,
                config,
                today=today,
                existing_species=species,
                existing_case_ids=case_ids,
                target_topics=target_topics,
                path=path.as_posix(),
                repo_root=repo_root,
                extra_findings=extra,
            )
        )
    return reviews


# --- rendering ---------------------------------------------------------------------

_STATUS_LABEL: dict[Status, str] = {
    "changes-requested": "❌ changes requested",
    "ready-for-expert-review": "🔬 ready for expert review",
    "ready-to-merge": "✅ ready to merge",
}


def render_markdown(reviews: list[ProposalReview]) -> str:
    """A committed-artifact-shaped review summary (same house style as the other audits)."""
    lines = [
        "# Corpus proposal review",
        "",
        "> Generated by `sprout propose check` (research item E5). Offline and deterministic:",
        "> a proposal's status is a pure function of the file, the shipped corpus, and the date.",
        "",
        "| Proposal | Species | Status | Errors | Warnings |",
        "|---|---|---|---|---|",
    ]
    for review in reviews:
        lines.append(
            f"| `{review.path}` | {review.species} | {_STATUS_LABEL[review.status]} | "
            f"{len(review.errors)} | {len(review.warnings)} |"
        )
    for review in reviews:
        lines += ["", f"## `{review.path}`", ""]
        if not review.findings:
            lines.append("No findings.")
        else:
            lines += ["| Severity | Code | Detail |", "|---|---|---|"]
            lines += [f"| {f.severity} | `{f.code}` | {f.detail} |" for f in review.findings]
        if review.status == "ready-for-expert-review":
            lines += [
                "",
                "Safety-bearing content with no committed sign-off. Per "
                "`docs/RESEARCH-ROADMAP.md` ('Validate with real users / risks') this needs a "
                "licensed veterinary toxicologist / poison-control clinician — and, for Spanish "
                "copy, a native horticulture reviewer — before it can merge.",
            ]
    lines.append("")
    return "\n".join(lines)


def render_json(reviews: list[ProposalReview]) -> str:
    payload = [{**review.model_dump(mode="json"), "status": review.status} for review in reviews]
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


# --- the fill-in-the-blanks template ------------------------------------------------

TEMPLATE = """\
# A Sprout corpus proposal — one new species, in every supported language, plus the
# eval case that proves the passage answers a real question.
#
#   sprout propose template > proposals/my-plant.yaml   # start here
#   sprout propose check proposals/my-plant.yaml        # review this one file
#   sprout propose check                                # what CI runs: every proposal
#
# Commit it under `proposals/` — that is where the merge-blocking gate looks, and a
# proposal filed anywhere else is reported as an error rather than skipped.
#
# Every field below is required unless marked optional. Nothing here is merged
# automatically: `check` tells you whether a maintainer *could* merge it.
schema_version: 1

# Lower-case, hyphenated corpus slug, and the botanical name a reviewer can verify.
species: my-plant
scientific_name: Genus species

submitter: your name or GitHub handle
submitted_date: '2026-01-31'

# true  -> original placeholder prose; the citation MUST use the example.invalid host.
# false -> transcribed from a real source; requires an `expert_review` sign-off below.
synthetic: true

provenance:
  source_name: Synthetic Plant-Care Notes
  url: https://example.invalid/my-plant
  license: CC0-1.0          # must be on the contribution allowlist
  fetch_date: '2026-01-31'  # ISO-8601 date the snapshot was taken
  topic: care

# One document per supported language, using the same '## <topic>' sections the corpus
# already uses. Sentences should name the plant (that is what makes verbatim extraction
# unambiguous), and no sentence may certify a plant "safe" — state what the source says.
documents:
  - language: en
    title: My plant care
    body: |
      ## Watering

      ...

      ## Light

      ...
  - language: es
    title: Cuidado de la My plant
    body: |
      ## Riego

      ...

      ## Luz

      ...

# The eval case your passage must satisfy: same schema as eval/suites/*.yaml.
eval_case:
  id: groundedness-my-plant-watering
  question: How often should I water my plant?
  expected_behavior: answer
  language: en
  sources:
    - my-plant.md
  expected_facts:
    - a phrase that appears verbatim in the passage above
  rationale: Why this case is worth gating on.
  provenance:
    source: synthetic
    license: CC0-1.0
    added: '2026-01-31'

# Representational-harm checklist. Every box must be true, and the ones a machine can
# falsify are cross-checked against the text.
harm_checklist:
  reviewer: your name or GitHub handle
  reviewed_date: '2026-01-31'
  common_names_regionally_neutral: true
  no_medicinal_or_edibility_claims: true
  traditional_knowledge_attributed: true
  plain_language_reviewed: true
  no_derogatory_or_stereotyped_framing: true
  notes: ''

# Optional, and required for non-synthetic or already-reviewed safety content. The
# artifact must be a committed Markdown sign-off under docs/audits/ that names this
# species, the reviewer, and the date they signed — pointing at any file that happens to
# exist does not discharge this gate.
# expert_review:
#   reviewer: Name
#   credential: DVM, DABVT
#   reviewed_date: '2026-01-31'
#   scope: toxicity prose and vet/poison-control routing, EN + ES
#   artifact: docs/audits/corpus-proposal-my-plant-review.md
"""
