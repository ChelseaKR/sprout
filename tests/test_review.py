"""Local review console (EXP-17): queue capture/label lifecycle and the three exporters.

Mirrors ``test_reminders.py``'s shape: a JSON-file-backed store with an injectable clock,
tested for persistence, capture gating, and round-tripping. The privacy contract itself
(off by default; caller must check config before calling ``capture``) is exercised at the
CLI layer in ``test_cli.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from sprout.answer_trace import AnswerTrace
from sprout.models import Answer, AnswerSentence, Chunk, Citation, RetrievedChunk
from sprout.review import (
    ReviewError,
    ReviewQueue,
    export_confidence_fit_cases,
    export_eval_case_drafts,
    export_judge_probes,
)


def _chunk(chunk_id: str = "c1") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id="d1",
        title="Pothos toxicity",
        source="pothos.md",
        text="Pothos is listed as toxic to cats and dogs by the cited source.",
        language="en",
        topic="toxicity",
        source_name="Synthetic Notes",
        url="https://example.invalid/pothos",
        license="CC0-1.0",
        fetch_date="2026-05-01",
    )


def _citation(chunk: Chunk) -> Citation:
    return Citation(
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        title=chunk.title,
        source=chunk.source,
        quote=chunk.text,
        license=chunk.license,
        fetch_date=chunk.fetch_date,
        url=chunk.url,
    )


def _low_confidence_trace(query: str = "is pothos toxic to my cat?") -> AnswerTrace:
    chunk = _chunk()
    citation = _citation(chunk)
    sentence = AnswerSentence(text=chunk.text, chunk_id=chunk.chunk_id, citation=citation)
    answer = Answer(
        question=query,
        language="en",
        sentences=(sentence,),
        retrieved=(RetrievedChunk(chunk=chunk, score=0.4),),
        confidence=0.35,
        low_confidence=True,
        is_safety_query=True,
        disclosure="Not veterinary advice.",
        as_of="2026-05-01",
    )
    return AnswerTrace(
        query=query,
        language="en",
        is_safety_query=True,
        safety_query_by_keyword=True,
        injection_categories=(),
        retrieved=(RetrievedChunk(chunk=chunk, score=0.4),),
        raw_candidates=((chunk.text, chunk.chunk_id),),
        answer=answer,
    )


def _refused_trace(query: str = "how do I fix a flat bicycle tire?") -> AnswerTrace:
    answer = Answer(
        question=query,
        language="en",
        refused=True,
        refusal_reason="out_of_scope",
        refusal_text="I don't have a cited reference that covers this.",
        confidence=0.0,
        disclosure="Not veterinary advice.",
    )
    return AnswerTrace(
        query=query,
        language="en",
        is_safety_query=False,
        safety_query_by_keyword=False,
        injection_categories=(),
        retrieved=(),
        raw_candidates=(),
        answer=answer,
    )


def _confident_trace(query: str = "how often should I water a snake plant?") -> AnswerTrace:
    chunk = _chunk(chunk_id="c2")
    citation = _citation(chunk)
    sentence = AnswerSentence(text=chunk.text, chunk_id=chunk.chunk_id, citation=citation)
    answer = Answer(
        question=query,
        language="en",
        sentences=(sentence,),
        retrieved=(RetrievedChunk(chunk=chunk, score=0.9),),
        confidence=0.95,
        low_confidence=False,
        disclosure="Not veterinary advice.",
        as_of="2026-05-01",
    )
    return AnswerTrace(
        query=query,
        language="en",
        is_safety_query=False,
        safety_query_by_keyword=False,
        injection_categories=(),
        retrieved=(RetrievedChunk(chunk=chunk, score=0.9),),
        raw_candidates=((chunk.text, chunk.chunk_id),),
        answer=answer,
    )


def _queue(tmp_path: Path, now: datetime = datetime(2026, 7, 8, tzinfo=UTC)) -> ReviewQueue:
    return ReviewQueue(tmp_path / "queue.json", clock=lambda: now)


# --- capture -----------------------------------------------------------------------


def test_capture_queues_low_confidence_and_refused(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    low = queue.capture(_low_confidence_trace())
    refused = queue.capture(_refused_trace())
    assert low is not None and low.reason == "low_confidence"
    assert refused is not None and refused.reason == "refused"
    assert {i.item_id for i in queue.all_items()} == {low.item_id, refused.item_id}


def test_capture_is_a_noop_for_confident_answers(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    assert queue.capture(_confident_trace()) is None
    assert queue.all_items() == []


def test_capture_persists_question_text_and_citations(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    item = queue.capture(_low_confidence_trace())
    assert item is not None
    assert item.question == "is pothos toxic to my cat?"
    assert item.citations[0].quote.startswith("Pothos is listed as toxic")
    # Reload from disk: the queue round-trips including the captured question text.
    reloaded = _queue(tmp_path)
    assert reloaded.get(item.item_id).question == item.question


def test_capture_drops_oldest_at_capacity(tmp_path: Path) -> None:
    queue = ReviewQueue(
        tmp_path / "queue.json", max_items=1, clock=lambda: datetime(2026, 7, 8, tzinfo=UTC)
    )
    first = queue.capture(_refused_trace("a"))
    second = queue.capture(_refused_trace("b"))
    assert first is not None and second is not None
    ids = {i.item_id for i in queue.all_items()}
    assert len(ids) == 1
    assert second.item_id in ids


# --- labeling ------------------------------------------------------------------------


def test_label_lifecycle(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    item = queue.capture(_low_confidence_trace())
    assert item is not None
    assert queue.unlabeled() == [item]
    updated = queue.label(item.item_id, "correct", note="matches the cited source")
    assert updated.label == "correct"
    assert updated.labeled_at is not None
    assert queue.unlabeled() == []
    assert queue.labeled() == [updated]


def test_label_rejects_unknown_label(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    item = queue.capture(_low_confidence_trace())
    assert item is not None
    with pytest.raises(ReviewError, match="unknown label"):
        queue.label(item.item_id, "definitely-wrong")


def test_label_rejects_unknown_id(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    with pytest.raises(ReviewError, match="no review item"):
        queue.label("nonexistent", "correct")


def test_remove(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    item = queue.capture(_low_confidence_trace())
    assert item is not None
    assert queue.remove(item.item_id) is True
    assert queue.remove(item.item_id) is False
    assert queue.all_items() == []


def test_unsupported_format_version_raises(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    path.write_text('{"format_version": 999, "items": []}', encoding="utf-8")
    with pytest.raises(ReviewError, match="unsupported"):
        ReviewQueue(path)


# --- exporters -------------------------------------------------------------------


def test_export_judge_probes_maps_label_to_human_label(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    correct = queue.capture(_low_confidence_trace("q-correct"))
    wrong = queue.capture(_low_confidence_trace("q-wrong"))
    unlabeled = queue.capture(_low_confidence_trace("q-unlabeled"))
    assert correct is not None and wrong is not None and unlabeled is not None
    queue.label(correct.item_id, "correct")
    queue.label(wrong.item_id, "wrong-plant")

    payload = export_judge_probes(queue.labeled())
    assert payload["labeled_date"]
    by_id = {p["id"]: p for p in payload["probes"]}
    assert by_id[f"review-{correct.item_id}"]["human_label"] is True
    assert by_id[f"review-{wrong.item_id}"]["human_label"] is False
    assert f"review-{unlabeled.item_id}" not in by_id
    assert all(p["kind"] == "entails" for p in payload["probes"])


def test_export_judge_probes_skips_refusals(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    item = queue.capture(_refused_trace())
    assert item is not None
    queue.label(item.item_id, "should-have-refused")
    payload = export_judge_probes(queue.labeled())
    assert payload["probes"] == []


def test_export_judge_probes_labeled_date_is_the_oldest_label_not_the_export_date(
    tmp_path: Path,
) -> None:
    """The freshness clock must not restart just because someone re-ran the exporter.

    `sprout calibrate` treats `labeled_date` as the 30-day judge-calibration freshness
    clock. This used to be stamped `date.today()`, so re-exporting a queue last labeled in
    January produced a file dated today and the staleness warning could never fire. It is
    now the oldest label date in the exported set -- a set is only as fresh as its stalest
    member.
    """
    queue = _queue(tmp_path)
    old = queue.capture(_low_confidence_trace("q-old"))
    recent = queue.capture(_low_confidence_trace("q-recent"))
    assert old is not None and recent is not None
    queue.label(old.item_id, "correct", as_of=datetime(2026, 1, 9, tzinfo=UTC))
    queue.label(recent.item_id, "correct", as_of=datetime(2026, 6, 30, tzinfo=UTC))

    payload = export_judge_probes(queue.labeled())

    assert payload["labeled_date"] == "2026-01-09"
    assert payload["labeled_date"] != date.today().isoformat()
    assert len(payload["probes"]) == 2


def test_export_judge_probes_omits_labeled_date_when_no_probe_is_exported(
    tmp_path: Path,
) -> None:
    """An export that dates nothing must not claim a date. A refusal-only queue produces
    zero probes; stamping today's date on that file would hand `calibrate` a freshness
    reading for a set with nothing in it."""
    queue = _queue(tmp_path)
    item = queue.capture(_refused_trace())
    assert item is not None
    queue.label(item.item_id, "should-have-refused")

    payload = export_judge_probes(queue.labeled())

    assert payload["probes"] == []
    assert "labeled_date" not in payload


def test_export_judge_probes_omits_labeled_date_when_a_label_carries_no_date(
    tmp_path: Path,
) -> None:
    """`labeled_at` is optional on the record. If any exported probe has none, the set's
    oldest label date is unknown, and unknown is reported by omission -- not by today."""
    queue = _queue(tmp_path)
    item = queue.capture(_low_confidence_trace())
    assert item is not None
    queue.label(item.item_id, "correct")
    undated = queue.get(item.item_id).model_copy(update={"labeled_at": None})

    payload = export_judge_probes([undated])

    assert len(payload["probes"]) == 1
    assert "labeled_date" not in payload


def test_export_confidence_fit_cases_carries_confidence_and_correctness(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    item = queue.capture(_low_confidence_trace())
    assert item is not None
    queue.label(item.item_id, "incomplete", note="missed the frequency detail")
    payload = export_confidence_fit_cases(queue.labeled())
    case = payload["cases"][0]
    assert case["confidence"] == pytest.approx(0.35)
    assert case["is_correct"] is False
    assert case["provenance"]["source"] == "local-review-queue"
    assert case["rationale"] == "missed the frequency detail"


def test_export_eval_case_drafts_marks_should_refuse(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    low = queue.capture(_low_confidence_trace())
    refused = queue.capture(_refused_trace())
    assert low is not None and refused is not None
    queue.label(low.item_id, "should-have-refused")
    queue.label(refused.item_id, "correct")

    payload = export_eval_case_drafts(queue.labeled())
    by_id = {c["id"]: c for c in payload["cases"]}
    assert by_id[f"review-draft-{low.item_id}"]["should_refuse"] is True
    assert by_id[f"review-draft-{low.item_id}"]["expected_behavior"] == "refuse-and-redirect"
    assert by_id[f"review-draft-{refused.item_id}"]["should_refuse"] is True
    assert "DRAFT" in by_id[f"review-draft-{low.item_id}"]["provenance"]["note"]


def test_exporters_skip_unlabeled_items(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    queue.capture(_low_confidence_trace())
    assert export_confidence_fit_cases(queue.all_items())["cases"] == []
    assert export_eval_case_drafts(queue.all_items())["cases"] == []


def test_cli_capture_precedence_refusal_wins_over_low_confidence(tmp_path: Path) -> None:
    # Every refusal also carries low_confidence=True, so the refusal opt-in must be
    # checked first: capture_on_low_confidence=false + capture_on_refusal=true still
    # captures refusals (the bug the review found made this combination capture nothing).
    from sprout.cli import _maybe_capture_review
    from sprout.config import Config

    cfg = Config.model_validate(
        {
            "review": {
                "enabled": True,
                "path": str(tmp_path / "queue.json"),
                "capture_on_low_confidence": False,
                "capture_on_refusal": True,
            }
        }
    )
    base = _refused_trace()
    # Real refusals always carry low_confidence=True (Assistant._refuse); mirror that
    # here so the test exercises exactly the combination the bug made unreachable.
    trace = base.model_copy(
        update={"answer": base.answer.model_copy(update={"low_confidence": True})}
    )
    assert trace.answer.refused and trace.answer.low_confidence
    _maybe_capture_review(cfg, trace)
    queue = ReviewQueue(cfg.review.path)
    assert len(queue) == 1
    assert queue.all_items()[0].reason == "refused"
