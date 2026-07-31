"""Bounded in-memory multi-turn conversation context — history as a selector, never a source.

EXP-07 (the designed replacement for the phantom ``ConversationConfig.session_memory`` field):
a follow-up ("what about in winter?", "¿y para los perros?") often omits the species/topic
named in an earlier turn. Restating it every turn is real chat-product friction, but letting
history answer *for* the assistant is exactly the grounding risk Sprout's provenance
architecture exists to control. The contract this module enforces:

* The ONLY thing carried across turns is a :class:`~sprout.models.Turn` — a species slug, a
  topic, and a language. Never the question text, never the answer text, never a citation.
* A ``Turn`` can only ever *widen which corpus passages* :class:`~sprout.retrieve.Retriever`
  is allowed to search (a species-filter fallback used only when the current turn names no
  species of its own — see ``Retriever._candidates``). It never adds words to a prompt, never
  bypasses the citation guard, and never appears in a rendered answer. There is no code path
  from ``SessionMemory`` into ``GenerationProvider`` or the citation guard, so a turn cannot
  manufacture or override a cited fact even in principle — see ``tests/test_conversation.py``
  for the adversarial proof and ``eval/suites/conversation.yaml`` for the harness-level cases.
* The window is bounded (``ConversationConfig.session_memory`` turns per session, default 4) and
  in-memory only — nothing is persisted to disk. A session cap bounds total memory even if a
  caller never signals a session has ended (the oldest session is evicted first).
* Process restart clears every session: this matches the "no database, no mutable server
  state to leak or subpoena" property the rest of Sprout already holds to
  (``docs/RESPONSIBLE-TECH-AUDITS.md`` §C).
"""

from __future__ import annotations

from collections import OrderedDict, deque

from .models import Answer, Turn
from .retrieve import species_slug

# A hard ceiling on concurrently-tracked sessions, independent of the per-session turn
# window (``ConversationConfig.session_memory``). Bounds total memory even if callers
# never signal a session has ended; the least-recently-used session is evicted first.
_DEFAULT_MAX_SESSIONS = 5000


class SessionMemory:
    """A bounded, in-memory-only turn window keyed by an opaque session id.

    Only :meth:`record` (fed by :func:`extract_turn`) writes into a session, and it only ever
    writes a :class:`Turn` — so there is no channel, malicious or accidental, for arbitrary
    text to enter the window.
    """

    def __init__(self, max_turns: int, max_sessions: int = _DEFAULT_MAX_SESSIONS) -> None:
        self._max_turns = max_turns
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, deque[Turn]] = OrderedDict()

    def record(self, session_id: str, turn: Turn) -> None:
        """Append ``turn`` to ``session_id``'s window; a ``max_turns=0`` config disables it."""
        if self._max_turns <= 0:
            return
        window = self._sessions.pop(session_id, None)
        if window is None:
            window = deque(maxlen=self._max_turns)
        window.append(turn)
        self._sessions[session_id] = window  # re-insert -> most-recently-used
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)  # evict least-recently-used

    def context_for(self, session_id: str) -> Turn | None:
        """The most recent turn that named a species, else the latest turn, else ``None``."""
        window = self._sessions.get(session_id)
        if not window:
            return None
        for turn in reversed(window):
            if turn.species_slug is not None:
                return turn
        return window[-1]

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def __len__(self) -> int:
        """Number of tracked sessions — for tests/observability; ids/content are never logged."""
        return len(self._sessions)


def extract_turn(answer: Answer) -> Turn:
    """Derive the selector-only :class:`Turn` from a rendered ``Answer`` — never its text.

    The species and topic come from the *retrieved, corpus-backed* chunk grounding the first
    rendered sentence — not from parsing the question or the answer prose — so there is no
    path for arbitrary user or model text to become a stored selector. A refusal (or an answer
    with no surviving sentences) carries no selector.
    """
    species: str | None = None
    topic: str | None = None
    if not answer.refused and answer.sentences:
        chunk_by_id = {rc.chunk.chunk_id: rc.chunk for rc in answer.retrieved}
        chunk = chunk_by_id.get(answer.sentences[0].chunk_id)
        if chunk is not None:
            species = species_slug(chunk.source)
            topic = chunk.topic
    return Turn(species_slug=species, topic=topic, language=answer.language)
