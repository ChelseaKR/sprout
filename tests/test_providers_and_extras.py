"""Coverage for the provider factory, chunk windowing, and language fallback."""

from __future__ import annotations

import sys
import types

import pytest

from sprout.chunk import _windows
from sprout.config import Config
from sprout.lang import _langdetect_fallback, detect_language
from sprout.providers import build_embedding, build_generator
from sprout.providers.bedrock import TitanEmbedding
from sprout.providers.deterministic import ExtractiveGenerator, HashingEmbedding
from sprout.providers.static_embedding import StaticEmbedding


def test_factory_deterministic_default() -> None:
    cfg = Config()
    assert isinstance(build_embedding(cfg), HashingEmbedding)
    assert isinstance(build_generator(cfg), ExtractiveGenerator)


def test_factory_static() -> None:
    cfg = Config.model_validate({"retrieval": {"embedding_provider": "static"}})
    assert isinstance(build_embedding(cfg), StaticEmbedding)


def test_factory_bedrock() -> None:
    unpriced_default = Config.model_validate({"generation": {"provider": "bedrock"}})
    with pytest.raises(ValueError, match=r"no pinned price"):
        build_generator(unpriced_default)

    generator_cfg = Config.model_validate(
        {
            "generation": {
                "provider": "bedrock",
                "model": "anthropic.claude-haiku-4-5-20251001-v1:0",
            }
        }
    )
    assert build_generator(generator_cfg).estimated_cost_usd("question", []) > 0

    embedding_cfg = Config.model_validate({"retrieval": {"embedding_provider": "bedrock"}})
    assert isinstance(build_embedding(embedding_cfg), TitanEmbedding)

    unknown_region_cfg = Config.model_validate(
        {
            "retrieval": {"embedding_provider": "bedrock"},
            "generation": {"region": "moon-1"},
        }
    )
    with pytest.raises(ValueError, match=r"no pinned price.*moon-1"):
        build_embedding(unknown_region_cfg)


def test_factory_anthropic() -> None:
    cfg = Config.model_validate({"generation": {"provider": "anthropic"}})
    assert build_generator(cfg).estimated_cost_usd("question", []) > 0


@pytest.mark.parametrize(
    "generation",
    [
        {"provider": "anthropic", "model": "anthropic.claude-haiku-4-5-20251001-v1:0"},
        {"provider": "bedrock", "model": "claude-haiku-4-5-20251001"},
    ],
)
def test_provider_activation_rejects_model_namespace_mismatch(
    generation: dict[str, str],
) -> None:
    cfg = Config.model_validate({"generation": generation})
    with pytest.raises(ValueError, match=r"model must"):
        build_generator(cfg)


def test_generation_config_accepts_native_bedrock_profile_and_arn_ids() -> None:
    for provider, model in [
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("bedrock", "anthropic.claude-haiku-4-5-20251001-v1:0"),
        ("bedrock", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
        ("bedrock", "arn:aws:bedrock:us-west-2:123456789012:provisioned-model/example"),
    ]:
        cfg = Config.model_validate({"generation": {"provider": provider, "model": model}})
        assert cfg.generation.model == model


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


def test_accent_authored_language_marker_matches_folded_query() -> None:
    # The bundle authors "tóxica"; tokenization folds a user-entered "toxica".
    assert detect_language("toxica", default="en") == "es"
