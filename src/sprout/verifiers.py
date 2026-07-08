"""The cloud-path entailment verifier (EXP-04) — a second, model-based gate behind the
citation guard, used only when the generator is non-deterministic (Claude/Bedrock).

The lexical citation guard (``guards.py::_supported_by``) is bag-of-tokens coverage plus a
negation-polarity check. It is airtight against fabrication (an unsupported sentence has no
lexical overlap with any chunk) but, per the model card's stated residual risk, it can admit
a *same-plant sentence recombination* — a cloud generator swapping which attribute applies
between two chunks about the same species, where each half individually clears the coverage
threshold. A cross-encoder NLI model reads the sentence and its cited chunk together and
scores whether the chunk actually *entails* the sentence, which is a materially different
(and stricter) check than shared vocabulary.

This module intentionally keeps model loading (``build_onnx_entailment_scorer``) separate
from the scoring contract (``EntailmentVerifier`` / ``NLIEntailmentVerifier``): the loader
needs ``onnxruntime`` + ``tokenizers`` (the ``sprout[nli]`` extra) and a network fetch from
the Hugging Face Hub, which the offline default must never require; the scoring contract
takes an injected ``score_fn`` so it is fully unit-testable with no model, no network, and
no extra dependency installed. ``guards.citation_guard`` depends only on the small
``EntailmentVerifier`` Protocol, never on this module's loader.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .config import NLIVerifierConfig
from .determinism import sha256_of_file


@runtime_checkable
class EntailmentVerifier(Protocol):
    """True iff ``premise`` (the cited chunk) entails ``hypothesis`` (the candidate sentence)."""

    def entails(self, premise: str, hypothesis: str) -> bool: ...

    @property
    def identity(self) -> str:
        """Short, human-readable identity folded into the eval run fingerprint/target."""
        ...


@dataclass(frozen=True)
class NLIEntailmentVerifier:
    """Cross-encoder NLI verifier: entailment probability >= ``threshold``.

    ``score_fn(premise, hypothesis)`` returns P(entailment) in [0, 1]. Real construction
    goes through :func:`build_onnx_entailment_scorer`; tests inject a stub directly so the
    threshold/identity logic here is exercised with zero model dependencies.
    """

    score_fn: Callable[[str, str], float]
    threshold: float
    model_id: str
    revision: str
    model_sha256: str

    def entails(self, premise: str, hypothesis: str) -> bool:
        return self.score_fn(premise, hypothesis) >= self.threshold

    @property
    def identity(self) -> str:
        return f"nli:{self.model_id}@{self.revision}:{self.model_sha256[:12]}:t{self.threshold}"


def build_onnx_entailment_scorer(cfg: NLIVerifierConfig) -> Callable[[str, str], float]:
    """Download (or reuse the local Hub cache of) the pinned ONNX NLI model and return a
    ``(premise, hypothesis) -> P(entailment)`` scorer running on CPU via onnxruntime.

    Requires the ``sprout[nli]`` extra (``onnxruntime``, ``tokenizers``, ``huggingface-hub``)
    — imported lazily here, exactly like ``providers/bedrock.py`` lazily imports ``boto3``,
    so the offline default never pays this cost. Fails closed: a missing extra, a failed
    download, or a hash mismatch against ``cfg.model_sha256`` raises rather than silently
    falling back to an unverified or absent verifier.
    """
    try:
        import numpy as np
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer
    except ImportError as exc:  # pragma: no cover - exercised via the nli extra only
        raise ImportError(
            "generation.support_verifier: 'nli' requires the 'sprout[nli]' extra "
            "(onnxruntime, tokenizers, huggingface-hub); install it or set "
            "generation.support_verifier back to 'lexical'"
        ) from exc

    if not cfg.model_sha256:  # pragma: no cover - guarded earlier by config validation too
        raise ValueError("NLIVerifierConfig.model_sha256 must be pinned before loading weights")

    model_path = hf_hub_download(
        repo_id=cfg.model_id, filename=cfg.onnx_filename, revision=cfg.revision
    )
    digest = sha256_of_file(model_path)
    if digest != cfg.model_sha256:
        raise ValueError(
            f"NLI model weight hash mismatch for {cfg.model_id}@{cfg.revision} "
            f"({cfg.onnx_filename}): expected {cfg.model_sha256}, got {digest} — refusing "
            "to load unpinned/tampered weights"
        )
    tokenizer_path = hf_hub_download(
        repo_id=cfg.model_id, filename=cfg.tokenizer_filename, revision=cfg.revision
    )
    tokenizer = Tokenizer.from_file(tokenizer_path)
    session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    input_names = {i.name for i in session.get_inputs()}
    label_index = cfg.entailment_label_index

    def score(premise: str, hypothesis: str) -> float:
        encoding = tokenizer.encode(premise, hypothesis)
        feed: dict[str, Any] = {
            "input_ids": np.array([encoding.ids], dtype=np.int64),
            "attention_mask": np.array([encoding.attention_mask], dtype=np.int64),
        }
        if "token_type_ids" in input_names:
            feed["token_type_ids"] = np.array([encoding.type_ids], dtype=np.int64)
        (logits,) = session.run(None, feed)
        row = logits[0]
        exp = np.exp(row - np.max(row))
        probs = exp / exp.sum()
        return float(probs[label_index])

    return score


def config_identity(cfg: NLIVerifierConfig) -> str:
    """The verifier's identity string computed from *config alone*, no model load/network.

    Used to fold the verifier's model, revision, weight hash, and threshold into the eval
    run fingerprint/target (EXP-04's "threshold and version go into the eval fingerprint")
    without forcing every `sprout eval` invocation to download model weights just to
    compute a fingerprint. Matches :attr:`NLIEntailmentVerifier.identity`'s format exactly.
    """
    sha = cfg.model_sha256 or "unpinned"
    return f"nli:{cfg.model_id}@{cfg.revision}:{sha[:12]}:t{cfg.entail_threshold}"


def build_verifier(cfg: NLIVerifierConfig) -> NLIEntailmentVerifier:
    """Construct the real, network-backed :class:`NLIEntailmentVerifier` from config."""
    assert cfg.model_sha256 is not None  # enforced by GenerationConfig's model_validator
    score_fn = build_onnx_entailment_scorer(cfg)
    return NLIEntailmentVerifier(
        score_fn=score_fn,
        threshold=cfg.entail_threshold,
        model_id=cfg.model_id,
        revision=cfg.revision,
        model_sha256=cfg.model_sha256,
    )
