"""EXP-04: the NLI-grade entailment verifier behind the citation guard (cloud path only).

Model loading (``verifiers.build_onnx_entailment_scorer``) needs the optional
``sprout[nli]`` extra and a network fetch, so it is exercised only through its real
``ImportError`` when the extra is absent (matching the offline-by-default posture) plus a
monkeypatched stand-in for the scoring function everywhere else — the scoring *contract*
(threshold, polarity-independent entailment check, config validation, wiring into the
citation guard) is fully covered without a model, network, or extra dependency.
"""

from __future__ import annotations

import pytest

from sprout.config import Config, GenerationConfig, NLIVerifierConfig
from sprout.guards import citation_guard
from sprout.models import Chunk, RetrievedChunk
from sprout.providers import build_entailment_verifier
from sprout.verifiers import NLIEntailmentVerifier, build_verifier, config_identity

_SHA = "a" * 64


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id="monstera",
        title="Monstera care",
        source="monstera.md",
        text=text,
        language="en",
        topic="general",
        source_name="Synthetic Plant-Care Notes",
        url="https://example.invalid/monstera.md",
        license="CC0-1.0",
        fetch_date="2026-05-01",
    )


def _verifier(score: float, threshold: float = 0.5) -> NLIEntailmentVerifier:
    return NLIEntailmentVerifier(
        score_fn=lambda p, h: score,
        threshold=threshold,
        model_id="m",
        revision="main",
        model_sha256=_SHA,
    )


# --- NLIEntailmentVerifier: pure scoring contract ---------------------------------------


def test_entails_true_at_or_above_threshold() -> None:
    assert _verifier(0.8).entails("premise", "hypothesis") is True


def test_entails_false_below_threshold() -> None:
    assert _verifier(0.2).entails("premise", "hypothesis") is False


def test_identity_includes_model_revision_hash_prefix_and_threshold() -> None:
    v = NLIEntailmentVerifier(
        score_fn=lambda p, h: 1.0,
        threshold=0.5,
        model_id="cross-encoder/nli-deberta-v3-xsmall",
        revision="abc123",
        model_sha256="f" * 64,
    )
    assert v.identity == "nli:cross-encoder/nli-deberta-v3-xsmall@abc123:ffffffffffff:t0.5"


def test_config_identity_matches_verifier_identity_format() -> None:
    cfg = NLIVerifierConfig(model_sha256="b" * 64, entail_threshold=0.7)
    ident = config_identity(cfg)
    assert ident == f"nli:{cfg.model_id}@{cfg.revision}:{'b' * 12}:t0.7"


def test_config_identity_handles_unpinned_hash() -> None:
    # model_sha256 is optional at the NLIVerifierConfig level (GenerationConfig enforces
    # pinning only when support_verifier is actually "nli"); config_identity must not crash.
    assert config_identity(NLIVerifierConfig()).startswith("nli:")


# --- GenerationConfig validation: fail closed, not silently -----------------------------


def test_nli_verifier_rejected_on_deterministic_provider() -> None:
    with pytest.raises(ValueError, match="deterministic"):
        GenerationConfig(support_verifier="nli", nli=NLIVerifierConfig(model_sha256="a" * 64))


def test_nli_verifier_requires_pinned_hash() -> None:
    with pytest.raises(ValueError, match="model_sha256"):
        GenerationConfig(provider="anthropic", support_verifier="nli")


def test_nli_verifier_accepted_on_cloud_path_with_pinned_hash() -> None:
    cfg = GenerationConfig(
        provider="anthropic", support_verifier="nli", nli=NLIVerifierConfig(model_sha256=_SHA)
    )
    assert cfg.support_verifier == "nli"


def test_lexical_default_never_requires_nli_config() -> None:
    assert Config().generation.support_verifier == "lexical"


# --- build_verifier(): wiring, with model loading monkeypatched -------------------------


def test_build_verifier_wires_config_into_scorer(monkeypatch: pytest.MonkeyPatch) -> None:
    import sprout.verifiers as verifiers_mod

    monkeypatch.setattr(verifiers_mod, "build_onnx_entailment_scorer", lambda cfg: lambda p, h: 0.9)
    cfg = NLIVerifierConfig(model_sha256="c" * 64, entail_threshold=0.6)
    v = build_verifier(cfg)
    assert v.threshold == 0.6
    assert v.model_sha256 == "c" * 64
    assert v.entails("chunk text", "sentence text") is True


def test_build_onnx_entailment_scorer_fails_closed_without_extra() -> None:
    # onnxruntime/tokenizers/huggingface_hub are not part of the base install; calling the
    # real loader without the `sprout[nli]` extra must raise, never silently no-op.
    from sprout.verifiers import build_onnx_entailment_scorer

    with pytest.raises(ImportError, match="sprout\\[nli\\]"):
        build_onnx_entailment_scorer(NLIVerifierConfig(model_sha256="d" * 64))


# --- providers.build_entailment_verifier(): factory switch -------------------------------


def test_build_entailment_verifier_none_for_lexical() -> None:
    assert build_entailment_verifier(Config()) is None


def test_build_entailment_verifier_builds_for_nli(monkeypatch: pytest.MonkeyPatch) -> None:
    import sprout.verifiers as verifiers_mod

    monkeypatch.setattr(verifiers_mod, "build_onnx_entailment_scorer", lambda cfg: lambda p, h: 1.0)
    cfg = Config.model_validate(
        {
            "generation": {
                "provider": "anthropic",
                "support_verifier": "nli",
                "nli": {"model_sha256": "e" * 64},
            }
        }
    )
    verifier = build_entailment_verifier(cfg)
    assert verifier is not None
    assert verifier.entails("premise", "hypothesis") is True


# --- citation_guard(): the actual safety-relevant integration ---------------------------


def test_citation_guard_drops_lexically_supported_but_not_entailed() -> None:
    """The recombination case the model card flags: two Monstera chunks share vocabulary,
    so a swapped-attribute sentence can clear lexical coverage against the *wrong* chunk
    while a real NLI model would not consider it entailed."""
    chunk = _chunk("mon-light", "Monstera prefers bright indirect light near a window.")
    retrieved = [RetrievedChunk(chunk=chunk, score=0.5)]
    candidates = [("Monstera prefers bright indirect light near a window.", "mon-light")]

    # Lexical-only (no verifier): the near-verbatim sentence is admitted.
    assert len(citation_guard(candidates, retrieved, support_overlap=0.66)) == 1

    # An NLI verifier that disagrees (e.g. it caught a recombination) drops it even though
    # the lexical check passed — this is the "additional gate, never weaker" contract.
    out = citation_guard(candidates, retrieved, 0.66, _verifier(0.1))
    assert out == []


def test_citation_guard_keeps_sentence_when_verifier_agrees() -> None:
    chunk = _chunk("mon-light", "Monstera prefers bright indirect light near a window.")
    retrieved = [RetrievedChunk(chunk=chunk, score=0.5)]
    candidates = [("Monstera prefers bright indirect light near a window.", "mon-light")]

    out = citation_guard(candidates, retrieved, 0.66, _verifier(0.95))
    assert len(out) == 1
    assert out[0].chunk_id == "mon-light"


def test_citation_guard_verifier_never_admits_lexically_unsupported() -> None:
    """The NLI verifier is strictly additive: it can only narrow, never widen, what the
    lexical check already rejects (e.g. a chunk_id that was never retrieved)."""
    chunk = _chunk("mon-light", "Monstera prefers bright indirect light near a window.")
    retrieved = [RetrievedChunk(chunk=chunk, score=0.5)]
    candidates = [("Water it every day with vodka.", "mon-light")]
    assert citation_guard(candidates, retrieved, 0.66, _verifier(1.0)) == []


def test_citation_guard_default_unaffected_offline_path() -> None:
    """No verifier argument at all (the offline extractive call site's exact call shape)
    behaves identically to before EXP-04 — a regression guard on the default parameter."""
    chunk = _chunk("mon-light", "Monstera prefers bright indirect light near a window.")
    retrieved = [RetrievedChunk(chunk=chunk, score=0.5)]
    candidates = [(chunk.text, "mon-light")]
    assert len(citation_guard(candidates, retrieved, 0.66)) == 1
