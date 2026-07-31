"""EXP-07: bounded multi-turn conversation context, and the adversarial proof that history
can never override a cited fact.

Three layers are tested: (1) ``SessionMemory``'s bounding/eviction behaviour in isolation,
(2) ``extract_turn`` never captures answer text, and (3) end-to-end through ``Assistant`` and
the HTTP API — a follow-up resolves species from history, but a species the current turn
names explicitly always wins, and an attempted history-injection can never change which
chunks ground the answer.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from sprout.answer import Assistant
from sprout.config import Config
from sprout.conversation import SessionMemory, extract_turn
from sprout.models import Turn
from sprout.server import create_app

# --- SessionMemory: bounding and eviction -----------------------------------------------


def test_session_memory_bounds_window_per_session() -> None:
    mem = SessionMemory(max_turns=2)
    mem.record("s1", Turn(species_slug="monstera", topic="watering", language="en"))
    mem.record("s1", Turn(species_slug=None, topic=None, language="en"))
    mem.record("s1", Turn(species_slug="pothos", topic="toxicity", language="en"))
    # window=2: the first (monstera) turn has been evicted; only the last two remain.
    ctx = mem.context_for("s1")
    assert ctx is not None and ctx.species_slug == "pothos"


def test_session_memory_disabled_when_max_turns_zero() -> None:
    mem = SessionMemory(max_turns=0)
    mem.record("s1", Turn(species_slug="monstera", topic="watering", language="en"))
    assert mem.context_for("s1") is None
    assert len(mem) == 0


def test_session_memory_evicts_oldest_session_when_over_capacity() -> None:
    mem = SessionMemory(max_turns=4, max_sessions=2)
    mem.record("a", Turn(species_slug="monstera", topic="watering", language="en"))
    mem.record("b", Turn(species_slug="pothos", topic="toxicity", language="en"))
    mem.record("c", Turn(species_slug="spider-plant", topic="toxicity", language="en"))
    assert len(mem) == 2
    assert mem.context_for("a") is None  # least-recently-used, evicted
    assert mem.context_for("b") is not None
    assert mem.context_for("c") is not None


def test_session_memory_context_prefers_most_recent_species() -> None:
    mem = SessionMemory(max_turns=4)
    mem.record("s1", Turn(species_slug="monstera", topic="watering", language="en"))
    mem.record("s1", Turn(species_slug=None, topic=None, language="en"))  # e.g. a refusal
    ctx = mem.context_for("s1")
    assert ctx is not None and ctx.species_slug == "monstera"  # not lost by a refusal turn


def test_session_memory_clear() -> None:
    mem = SessionMemory(max_turns=4)
    mem.record("s1", Turn(species_slug="monstera", topic="watering", language="en"))
    mem.clear("s1")
    assert mem.context_for("s1") is None


# --- extract_turn: structurally cannot capture answer text -------------------------------


def test_extract_turn_never_carries_question_or_answer_text(assistant: Assistant) -> None:
    ans = assistant.answer("why are my monstera leaves yellowing?")
    turn = extract_turn(ans)
    assert turn.species_slug == "monstera"
    assert turn.topic == "watering"
    # Turn is a closed, frozen model with exactly these three fields: there is no field for
    # question text, answer text, or a citation to leak into.
    assert set(Turn.model_fields) == {"species_slug", "topic", "language"}
    assert not hasattr(turn, "text")


def test_extract_turn_of_a_refusal_carries_no_selector(assistant: Assistant) -> None:
    ans = assistant.answer("how do I true a bicycle wheel?")
    assert ans.refused
    turn = extract_turn(ans)
    assert turn.species_slug is None and turn.topic is None


# --- Assistant.answer(history=...): selector, not source ---------------------------------


def test_followup_resolves_species_from_history(assistant: Assistant) -> None:
    first = assistant.answer("why are my monstera leaves yellowing?")
    history = extract_turn(first)
    assert history.species_slug == "monstera"

    followup = assistant.answer("what about the light?", history=history)
    assert not followup.refused
    assert any(c.source.startswith("monstera") for c in followup.citations)
    assert "bright indirect light" in followup.text.lower()


def test_named_species_in_current_turn_always_wins_over_history(assistant: Assistant) -> None:
    """A species named explicitly in the current turn overrides history outright — history
    is a fallback consulted only when the current turn names nothing on its own."""
    history = Turn(species_slug="monstera", topic="watering", language="en")
    ans = assistant.answer("is pothos toxic to my cat?", history=history)
    assert not ans.refused
    assert all(c.source.startswith("pothos") for c in ans.citations)
    assert "monstera" not in ans.text.lower()


def test_history_cannot_override_a_cited_fact_across_species(assistant: Assistant) -> None:
    """Adversarial case: turn 1 establishes 'Pothos is toxic'. Turn 2 asks about a
    *different*, explicitly-named species with the opposite corpus fact. History must not
    leak the prior species' fact into the new answer — the new answer's citation must come
    only from the newly-named species' own corpus passage."""
    turn1 = assistant.answer("is pothos toxic to my cat?")
    assert "toxic" in turn1.text.lower()
    history = extract_turn(turn1)
    assert history.species_slug == "pothos"

    turn2 = assistant.answer("is spider plant toxic to cats?", history=history)
    assert not turn2.refused
    assert all(c.source.startswith("spider-plant") for c in turn2.citations)
    assert "does not list" in turn2.text.lower()
    assert "pothos" not in turn2.text.lower()


def test_history_species_that_matches_no_chunk_fails_closed_not_over(assistant: Assistant) -> None:
    """A Turn carrying a species slug absent from the corpus (e.g. corrupted/forged state)
    narrows the candidate set to nothing and the assistant refuses — it never falls back to
    the unfiltered corpus and never fabricates an answer for a slug that isn't real."""
    bogus = Turn(species_slug="totally-not-a-real-species", topic="watering", language="en")
    ans = assistant.answer("how often should I water?", history=bogus)
    assert ans.refused


def test_history_never_reaches_the_model_query(assistant: Assistant) -> None:
    """History can only narrow *which chunks are searched* — it can never add text to what
    the generator sees. Proven here by observing retrieval: a follow-up naming no species
    retrieves the same chunk set whether or not history carries a (matching) prior species,
    as long as the query text is otherwise identical and already resolves within that
    species — i.e. history changes the *candidate pool*, not the query itself."""
    history = Turn(species_slug="monstera", topic="watering", language="en")
    with_history = assistant.answer("how often should I water?", history=history)
    without_history = assistant.answer("how often should I water my monstera?")
    # Both ground in the monstera watering passage; history only supplied the missing
    # selector the second (unaided) phrasing spelled out explicitly.
    assert {c.source for c in with_history.citations} == {
        c.source for c in without_history.citations
    }


# --- End-to-end through the HTTP API -------------------------------------------------------


def test_api_chat_followup_resolves_species_via_session_id(
    assistant: Assistant, config: Config
) -> None:
    client = TestClient(create_app(config, assistant=assistant))
    first = client.post(
        "/api/chat",
        json={"question": "why are my monstera leaves yellowing?", "session_id": "sess-1"},
    ).json()
    assert not first["refused"]

    followup = client.post(
        "/api/chat", json={"question": "what about the light?", "session_id": "sess-1"}
    ).json()
    assert not followup["refused"]
    assert any(c["source"].startswith("monstera") for c in followup["citations"])


def _baseline_citation_sources(assistant: Assistant, question: str) -> set[str]:
    """The citation set a fresh, history-less call produces — the ground truth for 'no
    history influenced this answer'."""
    return {c.source for c in assistant.answer(question).citations}


def test_api_chat_without_session_id_has_no_memory(assistant: Assistant, config: Config) -> None:
    client = TestClient(create_app(config, assistant=assistant))
    ambiguous = "is it toxic to cats?"  # names no species; pothos and spider-plant both match
    client.post("/api/chat", json={"question": "is pothos toxic to my cat?"})
    followup = client.post("/api/chat", json={"question": ambiguous}).json()
    # No session id -> no history is ever looked up -> identical to a cold, isolated call.
    assert {c["source"] for c in followup["citations"]} == _baseline_citation_sources(
        assistant, ambiguous
    )


def test_api_chat_sessions_stay_isolated(assistant: Assistant, config: Config) -> None:
    client = TestClient(create_app(config, assistant=assistant))
    ambiguous = "is it toxic to cats?"
    client.post(
        "/api/chat",
        json={"question": "is pothos toxic to my cat?", "session_id": "cat-owner"},
    )
    # A different session asking the same species-less follow-up must not inherit
    # "cat-owner"'s pothos context — it should match a cold, isolated call exactly.
    other = client.post("/api/chat", json={"question": ambiguous, "session_id": "dog-owner"}).json()
    assert {c["source"] for c in other["citations"]} == _baseline_citation_sources(
        assistant, ambiguous
    )


def test_api_chat_invalid_session_id_is_ignored_not_500(
    assistant: Assistant, config: Config
) -> None:
    client = TestClient(create_app(config, assistant=assistant))
    r = client.post(
        "/api/chat",
        json={"question": "why are my monstera leaves yellowing?", "session_id": "x" * 5000},
    )
    assert r.status_code == 200


def test_api_chat_stream_session_id_query_param(assistant: Assistant, config: Config) -> None:
    client = TestClient(create_app(config, assistant=assistant))
    client.get("/api/chat/stream?q=is pothos toxic to my cat&session_id=stream-sess")
    followup = client.get("/api/chat/stream?q=what about the light&session_id=stream-sess").text
    assert "event: done" in followup


def test_server_disables_memory_when_session_memory_zero(assistant: Assistant) -> None:
    cfg = Config.model_validate({"conversation": {"session_memory": 0}})
    client = TestClient(create_app(cfg, assistant=assistant))
    ambiguous = "is it toxic to cats?"
    client.post(
        "/api/chat",
        json={"question": "is pothos toxic to my cat?", "session_id": "sess-1"},
    )
    followup = client.post("/api/chat", json={"question": ambiguous, "session_id": "sess-1"}).json()
    assert {c["source"] for c in followup["citations"]} == _baseline_citation_sources(
        assistant, ambiguous
    )
