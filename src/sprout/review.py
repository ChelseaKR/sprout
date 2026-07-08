"""Local review console (EXP-17): opt-in capture + labeling of flagged/refused traces.

``Answer.low_confidence`` and ``Answer.refused`` already flag answers "for human
review" (``confidence.py``), but until now nothing captured them anywhere -- the signal
was computed and dropped on the floor. This module is the maintainer-side complement:
an opt-in local sink that queues flagged/refused traces (``ReviewQueue``), a labeling
workflow driven by ``sprout review``, and three exporters that turn labels into the
assets that currently starve for human judgments -- the judge probe set
(``eval/judge_probes.yaml``), the confidence re-fit dataset (FIX-08 / ADR-0013), and
draft eval cases for ``eval/suites/``.

**Privacy, first.** The queue is explicitly *not* the PII-free operational log
(``obs.py``'s ``Logger`` only ever writes a closed whitelist of fields) -- it is a
separate, user-consented capture file that stores the question text verbatim, because a
reviewer needs to actually see what was asked. It is:

- **off by default** (``ReviewConfig.enabled = False``; nothing is written until a
  maintainer opts in in ``config/sprout.yaml``),
- **local-only** (one JSON file on the maintainer's own machine; this module makes no
  network call, ever),
- **documented** with its own DPIA delta in ``docs/RESPONSIBLE-TECH-AUDITS.md`` (§C)
  and ``docs/adr/0014-local-review-console-for-flagged-answers.md``, the same discipline
  already applied to the photo-ID and reminders opt-in seams (ADR-0010, ADR-0011).

Exporters never write to the committed, authoritative files (``eval/judge_probes.yaml``,
``eval/suites/*.yaml``) directly -- they write standalone YAML a maintainer reviews and
hand-merges. One person's labels are one person's judgment; provenance says so
explicitly, and nothing here silently becomes part of a merge-blocking gate.

See ``docs/ideation/03-expansions.md`` EXP-17 for the design rationale this implements.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from .answer_trace import AnswerTrace
from .determinism import sha256_of_obj, short

_FORMAT_VERSION = 1

ReviewLabel = Literal["correct", "incomplete", "wrong-plant", "should-have-refused"]
LABELS: tuple[ReviewLabel, ...] = (
    "correct",
    "incomplete",
    "wrong-plant",
    "should-have-refused",
)

# A label counts as "what shipped was right" for exporters that need a boolean (judge-probe
# human_label, calibration is_correct). Only "correct" passes -- every other label,
# including "should-have-refused" (the assistant answered when it should have abstained),
# is a negative signal about the shipped behaviour.
_POSITIVE_LABELS: frozenset[str] = frozenset({"correct"})


class ReviewCitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    quote: str


class ReviewItem(BaseModel):
    """One captured trace, queued for a maintainer's label.

    Deliberately flat and self-contained: a reviewer judges the item from this record
    alone, without re-running the assistant against a (possibly since-changed) corpus.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    captured_at: str  # ISO-8601 UTC timestamp
    question: str
    language: str
    reason: Literal["low_confidence", "refused"]
    answer_text: str
    confidence: float
    refused: bool
    refusal_reason: str | None = None
    is_safety_query: bool = False
    citations: tuple[ReviewCitation, ...] = ()
    retrieved: tuple[str, ...] = ()  # "chunk_id (score)", most-relevant first
    label: ReviewLabel | None = None
    label_note: str = ""
    labeled_at: str | None = None

    @property
    def is_labeled(self) -> bool:
        return self.label is not None


class ReviewError(ValueError):
    """Raised on an invalid review-queue operation (unknown id, bad label, bad format)."""


class ReviewQueue:
    """A JSON-file-backed queue of ``ReviewItem``s. Clock-injectable for determinism.

    Mirrors ``reminders.ReminderStore``'s shape deliberately: local user data gets one
    small JSON file, loaded eagerly, saved on every mutation, no database.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_items: int = 500,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._path = Path(path)
        self._max = max_items
        self._clock = clock
        self._items: list[ReviewItem] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        if raw.get("format_version") != _FORMAT_VERSION:
            raise ReviewError(f"unsupported review-queue format: {raw.get('format_version')!r}")
        self._items = [ReviewItem.model_validate(i) for i in raw.get("items", [])]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": _FORMAT_VERSION,
            "items": [i.model_dump() for i in self._items],
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
        )

    def __len__(self) -> int:
        return len(self._items)

    def all_items(self) -> list[ReviewItem]:
        """All queued items, oldest-captured first."""
        return sorted(self._items, key=lambda i: (i.captured_at, i.item_id))

    def unlabeled(self) -> list[ReviewItem]:
        return [i for i in self.all_items() if not i.is_labeled]

    def labeled(self) -> list[ReviewItem]:
        return [i for i in self.all_items() if i.is_labeled]

    def get(self, item_id: str) -> ReviewItem:
        for i in self._items:
            if i.item_id == item_id:
                return i
        raise ReviewError(f"no review item with id {item_id!r}")

    def capture(self, trace: AnswerTrace) -> ReviewItem | None:
        """Queue ``trace`` if it is flagged low-confidence or refused; else no-op.

        The caller (the CLI today; ``serve`` could wire this the same way later) is
        responsible for checking ``ReviewConfig.enabled`` (and the per-reason capture
        flags) *before* calling this -- ``capture`` itself does not consult config, so it
        stays trivially testable and can never silently start capturing questions on its
        own if a caller forgets the gate.
        """
        answer = trace.answer
        reason: Literal["low_confidence", "refused"]
        if answer.refused:
            reason = "refused"
        elif answer.low_confidence:
            reason = "low_confidence"
        else:
            return None
        if len(self._items) >= self._max:
            # Best-effort background instrumentation: drop the oldest item rather than
            # raise. Capturing a trace must never be able to break the caller's request.
            self._items = self.all_items()[1:]
        now = self._clock()
        item_id = short(
            sha256_of_obj([trace.query, trace.language, now.isoformat(), len(self._items)])
        )
        item = ReviewItem(
            item_id=item_id,
            captured_at=now.isoformat(),
            question=trace.query,
            language=trace.language,
            reason=reason,
            answer_text=answer.display_text,
            confidence=answer.confidence,
            refused=answer.refused,
            refusal_reason=answer.refusal_reason,
            is_safety_query=trace.is_safety_query,
            citations=tuple(ReviewCitation(label=c.label, quote=c.quote) for c in answer.citations),
            retrieved=tuple(f"{rc.chunk.chunk_id} ({rc.score:.3f})" for rc in trace.retrieved),
        )
        self._items.append(item)
        self._save()
        return item

    def label(
        self,
        item_id: str,
        label: str,
        *,
        note: str = "",
        as_of: datetime | None = None,
    ) -> ReviewItem:
        if label not in LABELS:
            raise ReviewError(f"unknown label {label!r}; must be one of {LABELS}")
        now = as_of or self._clock()
        updated = self.get(item_id).model_copy(
            update={"label": label, "label_note": note, "labeled_at": now.isoformat()}
        )
        self._items = [updated if i.item_id == item_id else i for i in self._items]
        self._save()
        return updated

    def remove(self, item_id: str) -> bool:
        before = len(self._items)
        self._items = [i for i in self._items if i.item_id != item_id]
        removed = len(self._items) != before
        if removed:
            self._save()
        return removed


def _today(item: ReviewItem) -> str:
    return item.labeled_at[:10] if item.labeled_at else date.today().isoformat()


def export_judge_probes(
    items: Iterable[ReviewItem], *, id_prefix: str = "review"
) -> dict[str, Any]:
    """Labeled items -> ``eval.calibration.JudgeProbe``-shaped records, ``human_label`` set.

    Only rendered (non-refused) answers with at least one citation are probeable -- a
    refusal has no answer text for an entailment judge to check. ``human_label`` is True
    only for ``correct``: every other label means the rendered text should *not* be judged
    as entailed by its cited sources, which is exactly the ``entails`` probe question.
    Skips unlabeled items (no human judgment yet).
    """
    probes = [
        {
            "id": f"{id_prefix}-{item.item_id}",
            "kind": "entails",
            "text_a": item.answer_text,
            "sources": [c.quote for c in item.citations],
            "human_label": item.label in _POSITIVE_LABELS,
        }
        for item in items
        if item.label is not None and not item.refused and item.citations
    ]
    return {"labeled_date": date.today().isoformat(), "probes": probes}


def export_confidence_fit_cases(
    items: Iterable[ReviewItem], *, id_prefix: str = "review"
) -> dict[str, Any]:
    """Labeled items -> ``eval.dataset.DatasetItem``-shaped records for a confidence re-fit.

    ``confidence`` is the score the assistant actually produced for this trace;
    ``is_correct`` is the ground truth a re-fit (``sprout fit-confidence``, FIX-08 /
    ADR-0013) needs to compare it against. Provenance is marked ``local-review-queue`` so
    a re-fit run can tell single-reviewer evidence apart from the corpus-derived eval set.
    """
    cases = [
        {
            "id": f"{id_prefix}-{item.item_id}",
            "question": item.question,
            "provenance": {
                "source": "local-review-queue",
                "license": "internal-not-for-redistribution",
                "added": _today(item),
                "note": f"maintainer label={item.label!r} via `sprout review`",
            },
            "language": item.language,
            "expected_behavior": (
                "refuse-and-redirect"
                if (item.refused or item.label == "should-have-refused")
                else "answer"
            ),
            "confidence": item.confidence,
            "is_correct": item.label in _POSITIVE_LABELS,
            "rationale": item.label_note or f"reviewed trace ({item.reason}), label={item.label}",
        }
        for item in items
        if item.label is not None
    ]
    return {"cases": cases}


def export_eval_case_drafts(
    items: Iterable[ReviewItem], *, id_prefix: str = "review-draft"
) -> dict[str, Any]:
    """Labeled items -> DRAFT ``eval.dataset.DatasetItem``-shaped cases for curation.

    These are drafts, not committed suite cases: ``sprout eval`` only loads
    ``eval/suites/*.yaml``, so a maintainer must fact-check and move a draft into a suite
    file before it counts toward any gate. This exporter never writes there directly.
    """
    cases = []
    for item in items:
        if item.label is None:
            continue
        should_refuse = item.label == "should-have-refused" or item.refused
        cases.append(
            {
                "id": f"{id_prefix}-{item.item_id}",
                "question": item.question,
                "provenance": {
                    "source": "local-review-queue",
                    "license": "internal-not-for-redistribution",
                    "added": _today(item),
                    "note": "DRAFT from `sprout review` -- verify facts/citations before "
                    "moving into eval/suites/",
                },
                "language": item.language,
                "expected_behavior": "refuse-and-redirect" if should_refuse else "answer",
                "should_refuse": should_refuse,
                "sources": [c.quote for c in item.citations],
                "rationale": (
                    f"Captured via `sprout review` ({item.reason}); maintainer label="
                    f"{item.label!r}" + (f": {item.label_note}" if item.label_note else ".")
                ),
            }
        )
    return {"cases": cases}


def write_yaml(payload: dict[str, Any], out_path: str | Path) -> int:
    """Write an exporter's payload to ``out_path``. Returns the number of records written."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    records = payload.get("probes", payload.get("cases", []))
    return len(records)
