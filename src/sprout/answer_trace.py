"""The retrieval+generation trace surfaced under the CLI/server debug flag.

Every answer can be reproduced from its trace: the resolved language, whether it was
classified a safety query, any injection categories detected, the retrieved chunks with
scores, the raw generator candidates before guarding, and the final guarded answer. This
is the "every answer dumps its retrieval trace under a debug flag" affordance.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .models import Answer, RetrievedChunk


class AnswerTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    language: str
    is_safety_query: bool
    injection_categories: tuple[str, ...]
    retrieved: tuple[RetrievedChunk, ...]
    raw_candidates: tuple[tuple[str, str], ...]
    answer: Answer
