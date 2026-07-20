"""Record the live assistant's answers into a golden dataset for evaluation.

Authored cases carry only the question and expectations (sources/answers are NOT
hand-written). This step replays the real :class:`~sprout.answer.Assistant` over each
question and fills in ``target_response`` (what the user would see), ``sources`` (the cited
passages, so groundedness checks the answer against its own citations), ``confidence``, and a
measured ``is_correct`` label. Separating authored expectations from machine-recorded answers
keeps the scripted offline evaluation faithful to the engine and fully reproducible.

Cases with a non-empty ``history`` (EXP-07, the ``conversation`` suite) are replayed
turn-by-turn through a scratch :class:`~sprout.conversation.SessionMemory` bounded by the
*same* ``ConversationConfig.session_memory`` the live server uses, so the eval replay's window is
never more generous than what a real session gets. Only the resulting selector
(:class:`~sprout.models.Turn`) is carried forward into the final ``item.question`` call —
never the history questions' text, matching the server's own history-as-selector contract.
"""

from __future__ import annotations

from ..answer import Assistant
from ..config import Config
from ..conversation import SessionMemory, extract_turn
from ..guards import asserts_safety
from ..models import Answer, Turn
from ..text import coverage
from .dataset import Dataset, DatasetItem, TargetResponse

_FACT_COVERAGE = 0.6
_EVAL_SESSION_ID = "eval-replay"


def _is_correct(item: DatasetItem, ans: Answer, config: Config) -> bool:
    if item.should_refuse is not None:
        return ans.refused == item.should_refuse
    behavior = item.expected_behavior
    if behavior == "refuse-and-redirect":
        # Correct if it either refused (out-of-corpus) or handled the safety query
        # properly (routed to a vet, never certified safe).
        safe_handling = ans.safety_notice is not None and not asserts_safety(
            ans.display_text, ans.language, config.guards
        )
        return ans.refused or safe_handling
    if behavior == "answer":
        # A grounded (by construction) on-topic answer is correct; if expected facts were
        # authored, at least one must surface (the extractive answer may quote a different,
        # equally-grounded sentence). Refusing an answerable question is incorrect.
        if ans.refused:
            return False
        if not item.expected_facts:
            return True
        return any(coverage(fact, ans.text) >= _FACT_COVERAGE for fact in item.expected_facts)
    # "partial" or unspecified: any non-refusal that does not certify safety.
    return not ans.refused and not asserts_safety(ans.display_text, ans.language, config.guards)


def _replay_history(assistant: Assistant, history: list[str], config: Config) -> Turn | None:
    """Replay prior turns through a scratch, bounded session and return the resulting
    selector context — the same mechanism the live server uses, never the raw turn text."""
    memory = SessionMemory(max_turns=config.conversation.session_memory, max_sessions=1)
    for turn_question in history:
        ans = assistant.answer(turn_question)  # auto-detect language per historical turn
        memory.record(_EVAL_SESSION_ID, extract_turn(ans))
    return memory.context_for(_EVAL_SESSION_ID)


def record_item(assistant: Assistant, item: DatasetItem, config: Config) -> DatasetItem:
    history = _replay_history(assistant, item.history, config) if item.history else None
    ans = assistant.answer(
        item.question, item.language, history=history, season=item.season, light=item.light
    )
    # text holds only the cited claims (or the refusal prose); the routing directive lives
    # in safety_notice so groundedness never treats it as an ungrounded claim.
    text = ans.text if not ans.refused else (ans.refusal_text or "")
    target = TargetResponse(
        text=text,
        citations=[c.label for c in ans.citations],
        refused=ans.refused,
        confidence=ans.confidence,
        language=ans.language,
        safety_notice=ans.safety_notice,
    )
    return item.model_copy(
        update={
            "target_response": target,
            "sources": [c.quote for c in ans.citations],
            "confidence": ans.confidence,
            "is_correct": _is_correct(item, ans, config),
            "language": ans.language,
        }
    )


def record(assistant: Assistant, dataset: Dataset, config: Config) -> Dataset:
    """Replay the assistant over every case and return the golden dataset."""
    return Dataset.from_items([record_item(assistant, it, config) for it in dataset.items])
