"""The retrieval+generation trace surfaced under the CLI/server debug flag.

Every answer can be reproduced from its trace: the resolved language, whether the answer
routed to vet / poison-control and why, any injection categories detected, the retrieved
chunks with scores, the raw generator candidates before guarding, and the final guarded
answer. This is the "every answer dumps its retrieval trace under a debug flag"
affordance.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .models import Answer, RetrievedChunk


class AnswerTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    language: str

    #: The routing decision the answer actually took -- always equal to
    #: ``answer.is_safety_query``. Routing fires when the input-keyword classifier fires
    #: **or** the cited content is toxicity content (issue #107), so reporting only the
    #: classifier here told an operator ``safety=False`` about an answer that had just
    #: printed a poison-control card, and wrote that same false into the human review
    #: queue. The debug trace and the review record now describe what happened.
    is_safety_query: bool

    #: What the input-keyword classifier alone said (``guards.is_safety_query``). Kept
    #: as its own field, not folded into the one above, because the difference is the
    #: diagnostic: ``is_safety_query=True`` with this ``False`` is an answer that routed
    #: on its cited content rather than on the wording of the question.
    safety_query_by_keyword: bool

    injection_categories: tuple[str, ...]
    retrieved: tuple[RetrievedChunk, ...]
    raw_candidates: tuple[tuple[str, str], ...]
    answer: Answer
