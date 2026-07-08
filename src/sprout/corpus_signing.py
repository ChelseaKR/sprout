"""Signature verification for third-party corpus bundles (EXP-15).

Two schemes, chosen by the *installer's* ``corpus_registry.trusted_publishers`` config
entry for the bundle's claimed publisher id (never by the bundle itself):

- ``sigstore-keyless`` — the production path. Verifies a real Sigstore bundle (as
  produced by ``sigstore sign --bundle`` / ``cosign sign-blob --bundle``) against the
  public-good Sigstore instance: certificate chain to Fulcio's root, Rekor transparency
  log inclusion, and the signing identity (OIDC issuer + Subject Alternative Name).
  Requires the ``corpus`` extra (``pip install sprout[corpus]``) and network access to
  Sigstore's infrastructure — the same trust model as the release pipeline's
  cosign/SLSA posture, extended across the publisher trust boundary.
- ``dev-ed25519`` — a local keypair scheme for development and CI testing *only*. It has
  no transparency log and no third-party root of trust: whoever holds the private key
  can sign, and the installer trusts a public key it was configured with out of band.
  It exists so this module's enforcement logic is unit-testable offline; it must never
  be treated as equivalent to ``sigstore-keyless`` for a real third-party publisher.

Either way, verification happens against ``manifest.yaml``'s exact bytes *before*
anything else in the bundle is read — an unsigned or tampered bundle is unloadable by
construction (there is no code path that extracts a file before this succeeds).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import TrustedPublisher


class SignatureError(Exception):
    """The bundle's signature did not verify against the configured trust anchor."""


class MissingExtraError(SignatureError):
    """The ``corpus`` extra (``sigstore``) is not installed."""


@dataclass(frozen=True)
class VerifiedSignature:
    scheme: str
    identity: str


def verify_signature(
    manifest_bytes: bytes,
    *,
    scheme: str,
    signature_bytes: bytes,
    trusted: TrustedPublisher,
    _sigstore_verifier_factory: object | None = None,
) -> VerifiedSignature:
    """Verify ``manifest_bytes`` was signed per ``trusted`` (the config's trust anchor).

    ``scheme`` is the scheme the *bundle* shipped a signature file for; it must match
    ``trusted.signing_scheme`` or verification fails closed (a publisher cannot
    downgrade a sigstore-keyless trust entry to a dev-ed25519 signature).

    ``_sigstore_verifier_factory`` is test-only: it substitutes the object that talks to
    Sigstore's live infrastructure (default: the real public-good instance) so the
    surrounding logic verifies offline in CI.
    """
    if scheme != trusted.signing_scheme:
        raise SignatureError(
            f"bundle signed with scheme {scheme!r} but publisher {trusted.id!r} is "
            f"trusted only for {trusted.signing_scheme!r}"
        )
    if scheme == "dev-ed25519":
        return _verify_dev_ed25519(manifest_bytes, signature_bytes, trusted)
    if scheme == "sigstore-keyless":
        return _verify_sigstore_keyless(
            manifest_bytes, signature_bytes, trusted, verifier_factory=_sigstore_verifier_factory
        )
    raise SignatureError(f"unknown signing scheme: {scheme!r}")  # pragma: no cover


def _verify_dev_ed25519(
    manifest_bytes: bytes, signature_bytes: bytes, trusted: TrustedPublisher
) -> VerifiedSignature:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover - exercised via MissingExtraError test
        raise MissingExtraError(
            "verifying a dev-ed25519 bundle needs the 'corpus' extra: pip install 'sprout[corpus]'"
        ) from exc
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(trusted.identity))
    except ValueError as exc:
        raise SignatureError(f"malformed dev-ed25519 public key for {trusted.id!r}") from exc
    try:
        public_key.verify(signature_bytes, manifest_bytes)
    except InvalidSignature as exc:
        raise SignatureError(f"dev-ed25519 signature did not verify for {trusted.id!r}") from exc
    return VerifiedSignature(scheme="dev-ed25519", identity=trusted.identity)


def _production_verifier() -> object:  # pragma: no cover - thin factory, mocked in tests
    """Fetches Sigstore's current TUF trust root over the network on first use (cached
    locally after). Split out so tests can substitute a fake verifier without network.
    """
    from sigstore.verify import Verifier

    return Verifier.production()


def _verify_sigstore_keyless(
    manifest_bytes: bytes,
    signature_bytes: bytes,
    trusted: TrustedPublisher,
    *,
    verifier_factory: object | None = None,
) -> VerifiedSignature:
    """Verify against a real Sigstore bundle: certificate chain to Fulcio, Rekor
    transparency-log inclusion, and the signing identity (OIDC issuer + SAN). The
    network call is isolated in ``verifier_factory`` (default: the live public-good
    instance) so this method's own logic — bundle parsing, issuer requirement, identity
    policy, error translation — is unit-tested with a fake verifier, not skipped.
    """
    if trusted.issuer is None:
        raise SignatureError(f"publisher {trusted.id!r} has no OIDC issuer configured")
    try:
        from sigstore.errors import VerificationError
        from sigstore.models import Bundle
        from sigstore.verify import policy
    except ImportError as exc:
        raise MissingExtraError(
            "verifying a sigstore-keyless bundle needs the 'corpus' extra: "
            "pip install 'sprout[corpus]'"
        ) from exc

    try:
        bundle = Bundle.from_json(signature_bytes)
    except Exception as exc:
        raise SignatureError(f"malformed Sigstore bundle: {exc}") from exc

    ident = policy.Identity(identity=trusted.identity, issuer=trusted.issuer)
    verifier = (verifier_factory or _production_verifier)()  # type: ignore[operator]
    try:
        verifier.verify_artifact(manifest_bytes, bundle, ident)
    except VerificationError as exc:
        raise SignatureError(f"Sigstore verification failed for {trusted.id!r}: {exc}") from exc
    return VerifiedSignature(scheme="sigstore-keyless", identity=trusted.identity)
