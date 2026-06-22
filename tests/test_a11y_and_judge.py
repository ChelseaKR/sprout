"""Structural a11y checks, the transcript renderer, and the injectable LLM judge."""

from __future__ import annotations

import pytest

from sprout.a11y import AccessibilityError, assert_accessible, check_html, render_transcript
from sprout.eval.llm_judge import AnthropicJudge, _parse_score

_GOOD = (
    '<!doctype html><html lang="en"><head><title>Ok</title></head>'
    "<body><main><h1>Title</h1><h2>Sub</h2>"
    '<table><caption>C</caption><tr><th scope="col">A</th></tr></table>'
    "</main></body></html>"
)


def test_check_html_passes_clean_document() -> None:
    assert check_html(_GOOD) == []
    assert_accessible(_GOOD)  # does not raise


_HEAD = '<html lang="en"><head><title>t</title></head><body><h1>a</h1>'


@pytest.mark.parametrize(
    ("doc", "needle"),
    [
        ("<html><head><title>t</title></head><body><h1>x</h1></body></html>", "lang"),
        ('<html lang="en"><head></head><body><h1>x</h1></body></html>', "title"),
        ('<html lang="en"><head><title>t</title></head><body><p>no h1</p></body></html>', "h1"),
        (_HEAD + "<h3>skip</h3></body></html>", "jumps"),
        (_HEAD + '<img src="x"></body></html>', "alt"),
        (_HEAD + "<table><tr><th>A</th></tr></table></body></html>", "caption"),
        (_HEAD + '<a href="#" tabindex="3">x</a></body></html>', "tabindex"),
        (_HEAD + '<a href="#"></a></body></html>', "discernible"),
    ],
)
def test_check_html_flags_violations(doc: str, needle: str) -> None:
    problems = check_html(doc)
    assert any(needle in p for p in problems), problems


def test_assert_accessible_raises() -> None:
    with pytest.raises(AccessibilityError):
        assert_accessible("<html><body>no lang, no title, no h1</body></html>")


def test_render_transcript_is_accessible() -> None:
    doc = render_transcript(
        "Sprout transcript",
        [("Why yellow?", "Overwatering.", ["Monstera care — monstera.md (as of 2026-05-01)"])],
    )
    assert_accessible(doc)
    assert "Why yellow?" in doc
    assert "monstera.md" in doc


# --- LLM judge (offline, injected completion) ------------------------------------
def test_parse_score_extracts_json() -> None:
    assert _parse_score('here: {"score": 0.9, "reason": "ok"}')[0] == 0.9
    with pytest.raises(ValueError, match="no JSON"):
        _parse_score("no object here")
    with pytest.raises(ValueError, match="malformed"):
        _parse_score('{"score": "not-a-number"}')


def test_anthropic_judge_with_injected_completion() -> None:
    calls: list[str] = []

    def fake(system: str, user: str) -> str:
        calls.append(user)
        return '{"score": 0.95, "reason": "entailed"}'

    judge = AnthropicJudge(completion=fake)
    # Judge model differs from the answer model (Haiku) — judge != answer model.
    assert judge.config["model"] == "claude-sonnet-4-6"
    decision = judge.entails("claim", ["source"])
    assert decision.passed and decision.score == 0.95
    assert judge.contains("answer", "fact").passed
    assert judge.equivalent("a", "b").passed
    assert len(calls) == 3
    assert judge.config_hash  # stable hash over the pinned config
