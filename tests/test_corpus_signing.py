"""Signature verification unit tests (EXP-15): both schemes, offline.

``dev-ed25519`` is exercised with real Ed25519 keys (no network). ``sigstore-keyless``
is exercised by injecting a fake verifier/bundle so the policy-construction and
error-translation logic runs for real without touching Sigstore's live infrastructure.
"""

from __future__ import annotations

import sys

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sprout.config import TrustedPublisher
from sprout.corpus_signing import MissingExtraError, SignatureError, verify_signature


def _publisher(**overrides: object) -> TrustedPublisher:
    base: dict[str, object] = {
        "id": "acme-botanicals",
        "name": "Acme Botanicals",
        "signing_scheme": "dev-ed25519",
        "identity": "",
    }
    base.update(overrides)
    return TrustedPublisher.model_validate(base)


def test_dev_ed25519_round_trip_ok() -> None:
    key = Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    manifest_bytes = b"hello corpus manifest"
    sig = key.sign(manifest_bytes)

    trusted = _publisher(identity=pub_hex)
    result = verify_signature(
        manifest_bytes, scheme="dev-ed25519", signature_bytes=sig, trusted=trusted
    )
    assert result.scheme == "dev-ed25519"
    assert result.identity == pub_hex


def test_dev_ed25519_wrong_signature_fails_closed() -> None:
    key = Ed25519PrivateKey.generate()
    other_key = Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    manifest_bytes = b"hello corpus manifest"
    bad_sig = other_key.sign(manifest_bytes)  # signed with the wrong key

    trusted = _publisher(identity=pub_hex)
    with pytest.raises(SignatureError):
        verify_signature(
            manifest_bytes, scheme="dev-ed25519", signature_bytes=bad_sig, trusted=trusted
        )


def test_dev_ed25519_tampered_manifest_fails_closed() -> None:
    key = Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    sig = key.sign(b"original manifest bytes")

    trusted = _publisher(identity=pub_hex)
    with pytest.raises(SignatureError):
        verify_signature(
            b"tampered manifest bytes", scheme="dev-ed25519", signature_bytes=sig, trusted=trusted
        )


def test_dev_ed25519_malformed_public_key() -> None:
    trusted = _publisher(identity="not-hex")
    with pytest.raises(SignatureError):
        verify_signature(b"x", scheme="dev-ed25519", signature_bytes=b"y", trusted=trusted)


def test_scheme_mismatch_rejected() -> None:
    # A bundle signed dev-ed25519 cannot satisfy a publisher trusted only for
    # sigstore-keyless (or vice versa) — the config's scheme wins, not the bundle's.
    trusted = _publisher(
        signing_scheme="sigstore-keyless", identity="pub@example.com", issuer="https://x"
    )
    with pytest.raises(SignatureError, match="trusted only for"):
        verify_signature(b"x", scheme="dev-ed25519", signature_bytes=b"y", trusted=trusted)


def test_dev_ed25519_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.asymmetric.ed25519", None)
    trusted = _publisher(identity="00" * 32)
    with pytest.raises(MissingExtraError):
        verify_signature(b"x", scheme="dev-ed25519", signature_bytes=b"y", trusted=trusted)


class _FakeVerifier:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: list[tuple[bytes, object, object]] = []

    def verify_artifact(self, data: bytes, bundle: object, policy_: object) -> None:
        self.calls.append((data, bundle, policy_))
        if self.should_fail:
            from sigstore.errors import VerificationError

            raise VerificationError("fake: identity mismatch")


# Constructing a byte-perfect real Sigstore bundle (valid cert chain + Rekor log entry)
# is Sigstore's own wire format, not this module's logic — these tests instead
# monkeypatch ``Bundle.from_json`` with a sentinel, so what's actually under test is
# *our* code: issuer requirement, identity-policy construction, and error translation.
_SENTINEL_BUNDLE = object()


@pytest.fixture(autouse=True)
def _stub_bundle_from_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from sigstore.models import Bundle

    monkeypatch.setattr(Bundle, "from_json", staticmethod(lambda _b: _SENTINEL_BUNDLE))


def test_sigstore_keyless_ok_with_injected_verifier() -> None:
    trusted = _publisher(
        signing_scheme="sigstore-keyless",
        identity="publisher@example.com",
        issuer="https://accounts.example.com",
    )
    fake = _FakeVerifier(should_fail=False)
    manifest_bytes = b"manifest bytes"

    result = verify_signature(
        manifest_bytes,
        scheme="sigstore-keyless",
        signature_bytes=b'{"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"}',
        trusted=trusted,
        _sigstore_verifier_factory=lambda: fake,
    )
    assert result.scheme == "sigstore-keyless"
    assert result.identity == "publisher@example.com"
    assert fake.calls and fake.calls[0][0] == manifest_bytes
    assert fake.calls[0][1] is _SENTINEL_BUNDLE


def test_sigstore_keyless_verification_failure_fails_closed() -> None:
    trusted = _publisher(
        signing_scheme="sigstore-keyless",
        identity="publisher@example.com",
        issuer="https://accounts.example.com",
    )
    fake = _FakeVerifier(should_fail=True)

    with pytest.raises(SignatureError, match="Sigstore verification failed"):
        verify_signature(
            b"manifest bytes",
            scheme="sigstore-keyless",
            signature_bytes=b"{}",
            trusted=trusted,
            _sigstore_verifier_factory=lambda: fake,
        )


def test_sigstore_keyless_requires_issuer() -> None:
    trusted = _publisher(signing_scheme="sigstore-keyless", identity="publisher@example.com")
    with pytest.raises(SignatureError, match="OIDC issuer"):
        verify_signature(
            b"x",
            scheme="sigstore-keyless",
            signature_bytes=b"{}",
            trusted=trusted,
            _sigstore_verifier_factory=lambda: _FakeVerifier(),
        )


def test_sigstore_keyless_malformed_bundle_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from sigstore.models import Bundle

    def _raise(_b: bytes) -> None:
        raise ValueError("bad json")

    monkeypatch.setattr(Bundle, "from_json", staticmethod(_raise))
    trusted = _publisher(
        signing_scheme="sigstore-keyless", identity="p@example.com", issuer="https://x"
    )
    with pytest.raises(SignatureError, match="malformed Sigstore bundle"):
        verify_signature(
            b"x",
            scheme="sigstore-keyless",
            signature_bytes=b"not json at all {{{",
            trusted=trusted,
            _sigstore_verifier_factory=lambda: _FakeVerifier(),
        )


def test_sigstore_keyless_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sigstore.verify", None)
    trusted = _publisher(
        signing_scheme="sigstore-keyless", identity="p@example.com", issuer="https://x"
    )
    with pytest.raises(MissingExtraError):
        verify_signature(
            b"x",
            scheme="sigstore-keyless",
            signature_bytes=b"{}",
            trusted=trusted,
            _sigstore_verifier_factory=lambda: _FakeVerifier(),
        )
