"""Coverage for the provider factory, chunk windowing, and language fallback."""

from __future__ import annotations

import sys
import types

import pytest

from sprout.chunk import _windows
from sprout.config import Config
from sprout.lang import _langdetect_fallback, detect_language
from sprout.providers import build_embedding, build_generator
from sprout.providers.anthropic_native import AnthropicGenerator
from sprout.providers.bedrock import BedrockGenerator, TitanEmbedding
from sprout.providers.deterministic import ExtractiveGenerator, HashingEmbedding


def test_factory_deterministic_default() -> None:
    cfg = Config()
    assert isinstance(build_embedding(cfg), HashingEmbedding)
    assert isinstance(build_generator(cfg), ExtractiveGenerator)


def test_factory_bedrock() -> None:
    cfg = Config.model_validate(
        {"retrieval": {"embedding_provider": "bedrock"}, "generation": {"provider": "bedrock"}}
    )
    assert isinstance(build_embedding(cfg), TitanEmbedding)
    assert isinstance(build_generator(cfg), BedrockGenerator)


def test_factory_anthropic() -> None:
    cfg = Config.model_validate({"generation": {"provider": "anthropic"}})
    assert isinstance(build_generator(cfg), AnthropicGenerator)


def test_chunk_windows_split_and_overlap() -> None:
    sentences = [f"Sentence number {i} about watering plants." for i in range(20)]
    windows = _windows(sentences, max_words=12, overlap_words=6)
    assert len(windows) > 1  # long section split into multiple windows
    # Overlap: the tail of one window reappears at the head of the next.
    first_tail = windows[0].split(".")[-2].strip()
    assert first_tail and first_tail in windows[1]


def test_langdetect_fallback_without_dependency() -> None:
    # langdetect is not a runtime dependency, so the fallback returns the default.
    assert _langdetect_fallback("ambiguous 123", "en") == "en"


def test_langdetect_fallback_with_fake_module(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("langdetect")
    fake.detect = lambda text: "es"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langdetect", fake)
    assert _langdetect_fallback("hola", "en") == "es"

    fake.detect = lambda text: "pt"  # type: ignore[attr-defined]  # unsupported -> default
    assert _langdetect_fallback("texto", "en") == "en"

    def boom(text: str) -> str:
        raise RuntimeError("no features")

    fake.detect = boom  # type: ignore[attr-defined]
    assert _langdetect_fallback("", "es") == "es"


def test_detect_language_tie_uses_fallback() -> None:
    # Equal marker scores route through the fallback (which returns the default).
    assert detect_language("plant water the and", default="en") in {"en", "es"}
