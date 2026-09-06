"""Coverage for the provider factory, chunk windowing, and language fallback."""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
import types

import pytest

from sprout.chunk import _windows
from sprout.config import Config
from sprout.eval.stats import Z_95, wilson_interval
from sprout.lang import _langdetect_fallback, detect_language
from sprout.providers import build_embedding, build_generator
from sprout.providers.base import context_hint, l2_normalize
from sprout.providers.bedrock import TitanEmbedding
from sprout.providers.deterministic import ExtractiveGenerator, HashingEmbedding
from sprout.providers.static_embedding import StaticEmbedding
from sprout.text import content_tokens


def test_context_hint_empty_for_no_selector() -> None:
    assert context_hint(frozenset()) == ""


def test_context_hint_names_the_selector_terms_as_non_source() -> None:
    hint = context_hint(frozenset({"winter"}))
    assert "winter" in hint
    assert "not a source" in hint
    assert "not a fact" in hint


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


# --- square roots that are the same on every machine -------------------------------


def _reference_l2(vec: list[float]) -> list[float]:
    """L2-normalise with ``math.sqrt``, the correctly-rounded IEEE 754 square root."""
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def _pow_l2(vec: list[float]) -> list[float]:
    """What the embedders used to do: ``x ** 0.5``, which is libm's ``pow``."""
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm else vec


def _vectors_pow_and_sqrt_normalise_differently(limit: int = 5) -> list[list[float]]:
    """Vectors the two square roots give *different normalised output* for, on this box.

    A last-bit difference in the norm often washes out in the division, so it is not
    enough to find inputs whose norms differ — the search keeps only the ones that
    survive into the returned vector. Which inputs those are depends on the platform's
    libm, so they are searched for rather than hard-coded; glibc's ``pow`` is correctly
    rounded for these, and the caller skips when the search comes up empty.
    """
    rng = random.Random(7)
    found: list[list[float]] = []
    for _ in range(200_000):
        if len(found) >= limit:
            break
        vec = [rng.uniform(-1.0, 1.0) for _ in range(rng.randint(2, 16))]
        if _pow_l2(vec) != _reference_l2(vec):
            found.append(vec)
    return found


def test_l2_normalize_is_the_correctly_rounded_square_root() -> None:
    """``x ** 0.5`` is ``pow``, which IEEE 754 does not require to be correctly rounded.

    ``web-static/src/hashEmbedding.ts`` — the port that runs the live site — normalises
    with ``Math.sqrt`` while the embedders here normalised with ``pow``, so the two
    surfaces this repo claims agree bit-for-bit were using different square roots for the
    same pipeline. And since #122 the committed eval artifacts are byte-compared against
    a fresh regeneration, which turns any last-bit platform difference into a red build on
    a file nobody edited (as it already did once, for ``static_vectors.json``).
    """
    separating = _vectors_pow_and_sqrt_normalise_differently()
    if not separating:
        pytest.skip("this platform's pow is correctly rounded for every searched input")
    for vec in separating:
        assert l2_normalize(vec) == _reference_l2(vec)
        assert l2_normalize(vec) != _pow_l2(vec)


def test_the_hashing_embedder_normalises_with_sqrt() -> None:
    """Rebuild the raw pre-normalisation vector and compare the whole pipeline.

    Testing ``l2_normalize`` alone would stay green while an embedder kept its own inline
    ``** 0.5``, which is the state this replaced.
    """
    dim = 512
    text = "why are my monstera leaves yellow and drooping in winter"
    raw = [0.0] * dim
    for tok in content_tokens(text):
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        raw[int.from_bytes(digest[:4], "big") % dim] += 1.0 if digest[4] & 1 else -1.0
    assert any(raw), "the probe text produced an all-zero vector"
    assert HashingEmbedding(dim=dim).embed(text) == _reference_l2(raw)


def test_the_static_embedder_normalises_with_sqrt() -> None:
    embedder = StaticEmbedding()
    text = "riego de la monstera en invierno con poca luz"
    raw = [0.0] * embedder.dim
    for tok in content_tokens(text):
        known = embedder._table.vectors.get(tok)
        contribution = known if known is not None else embedder._fallback(tok)
        for i, v in enumerate(contribution):
            raw[i] += v
    assert any(raw), "the probe text produced an all-zero vector"
    assert embedder.embed(text) == _reference_l2(raw)


def test_the_titan_embedder_normalises_with_sqrt() -> None:
    """Titan's vector arrives over the wire, so feed it one that separates the two roots."""
    separating = _vectors_pow_and_sqrt_normalise_differently(limit=1)
    if not separating:
        pytest.skip("this platform's pow is correctly rounded for every searched input")
    payload = separating[0]

    class _Body:
        @staticmethod
        def read() -> bytes:
            return json.dumps({"embedding": payload}).encode("utf-8")

    class _Client:
        @staticmethod
        def invoke_model(**_: object) -> dict[str, object]:
            return {"body": _Body()}

    embedder = TitanEmbedding(dim=len(payload), client=_Client())
    assert embedder.embed("anything") == _reference_l2(payload)


def _wilson_interval_pow(successes: int, n: int) -> tuple[float, float]:
    """What ``wilson_interval`` computed before: ``x ** 0.5`` for the margin."""
    z = Z_95
    phat = successes / n
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * ((phat * (1 - phat) / n + z * z / (4 * n * n)) ** 0.5)
    return (max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom))


def _wilson_interval_sqrt(successes: int, n: int) -> tuple[float, float]:
    """The correctly-rounded reference: ``math.sqrt`` for the margin."""
    z = Z_95
    phat = successes / n
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom))


def _wilson_inputs_that_separate_pow_from_sqrt(limit: int = 5) -> list[tuple[int, int]]:
    """(successes, n) pairs whose *interval*, not merely its margin, differs.

    A last-bit difference in the margin usually washes out in the division, so the search
    keeps only the pairs that survive into the returned bounds. On macOS (arm64, CPython
    3.12.14) the first is (42, 62) -- a suite size this harness reaches.
    """
    found: list[tuple[int, int]] = []
    for n in range(1, 601):
        if len(found) >= limit:
            break
        for successes in range(n + 1):
            if len(found) >= limit:
                break
            if _wilson_interval_pow(successes, n) != _wilson_interval_sqrt(successes, n):
                found.append((successes, n))
    return found


def test_the_wilson_margin_uses_the_correctly_rounded_square_root() -> None:
    """The interval is printed into the byte-compared eval report.

    Measured on macOS 2026-09-01: 99 of the 80600 (successes, n) pairs with n<=400 give a
    different *margin* under ``pow`` than under ``sqrt``, and the first whose published
    *bounds* differ is 42 of 62 -- an item count this harness reaches. None of those
    changed the report's 3-decimal figure today, which is the difference between "not
    currently broken" and "cannot break": since #122 the gate compares bytes, and glibc's
    ``pow`` agrees with ``sqrt`` where macOS's does not, so the disagreement is between
    the laptop and the runner.
    """
    separating = _wilson_inputs_that_separate_pow_from_sqrt()
    if not separating:
        pytest.skip("this platform's pow is correctly rounded for every searched input")

    for successes, n in separating:
        assert wilson_interval(successes, n) == _wilson_interval_sqrt(successes, n)
        assert wilson_interval(successes, n) != _wilson_interval_pow(successes, n)


def test_no_published_statistic_is_computed_with_pow() -> None:
    """No ``x ** 0.5`` anywhere in ``eval/stats.py`` — not just in ``wilson_interval``.

    The two functions in this module both print into ``docs/audits/eval-report.*``, which
    is byte-compared against a fresh regeneration (#122). Pinning only ``wilson_interval``
    let the next one in: ``wilson_difference_interval`` arrived with two inline
    ``** 0.5`` calls and merged cleanly beside the fix that removed the first one, because
    git had no reason to see a contradiction between an addition and a deletion in
    different hunks. This asserts the property over the whole module, so the next
    statistic cannot reintroduce the platform-dependent root either.
    """
    import ast
    from pathlib import Path

    source = Path("src/sprout/eval/stats.py").read_text(encoding="utf-8")
    offenders = [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Pow)
        and isinstance(node.right, ast.Constant)
        and node.right.value == 0.5
    ]
    assert not offenders, (
        f"src/sprout/eval/stats.py computes a square root with pow at line(s) {offenders}; "
        "use math.sqrt so the published bounds are the same bytes on every platform"
    )
