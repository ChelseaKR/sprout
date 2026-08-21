"""Verify and install signed third-party corpus bundles (EXP-15).

``verify_bundle`` enforces, in order, before any passage content is readable by the
caller: the archive layout is safe (no path traversal, no non-regular-file members, no
oversized members); the publisher is one this install trusts
(``corpus_registry.trusted_publishers``); the signature verifies against that trust
entry; every document/toxicity/suite license is in the allowlist; and the manifest's
``file_hashes`` tree matches every other file in the archive byte-for-byte. Any failure
raises ``CorpusBundleError`` (or ``SignatureError``) — there is no partial-success path.

``install_bundle`` calls ``verify_bundle`` first, then extracts into
``corpus_registry.registry_path/<publisher>/<name>/<version>/`` and writes a
``PROVENANCE.json`` sidecar recording the publisher and the exact signature that
verified. It never writes to ``corpus.path``, ``corpus.manifest``, or ``config/`` — an
installed bundle lives in its own namespace, separate from Sprout's own corpus and
config, so it cannot override the routing/deny-list strings ``guards.*`` in
``config.py`` (those are never sourced from a registry install).

Wiring an installed bundle into live retrieval — so its passages are queryable and its
citations render a publisher-provenance banner — is deliberately out of scope for this
change; see ``docs/corpus-bundle-format.md`` for the follow-up.
"""

from __future__ import annotations

import json
import shutil
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import Config, TrustedPublisher
from .corpus_bundle import ALLOWED_MEMBER_PREFIXES, BundleError, BundleManifest, parse_manifest
from .corpus_signing import VerifiedSignature, verify_signature
from .determinism import sha256_of_bytes

MANIFEST_NAME = "manifest.yaml"
_SIGNATURE_MEMBER = {
    "sigstore-keyless": "signature/sigstore.json",
    "dev-ed25519": "signature/dev.sig",
}


class CorpusBundleError(BundleError):
    """A bundle failed verification: bad archive layout, untrusted publisher, license
    not allowlisted, or a content-hash mismatch (tampering). Fails closed.

    Subclasses ``corpus_bundle.BundleError`` (raised for a malformed manifest) so
    callers can catch one base type for "this bundle is not installable"."""


@dataclass(frozen=True)
class VerificationReport:
    manifest: BundleManifest
    manifest_bytes: bytes
    signature: VerifiedSignature


@dataclass(frozen=True)
class InstalledCorpus:
    publisher_id: str
    name: str
    version: str
    install_path: Path
    provenance_path: Path


def _read(tf: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    fh = tf.extractfile(member)
    if fh is None:  # pragma: no cover - defensive; _members() already excludes non-files
        raise CorpusBundleError(f"could not read bundle member: {member.name!r}")
    return fh.read()


def _open_bundle(bundle_path: Path, max_bytes: int) -> tarfile.TarFile:
    if not bundle_path.exists():
        raise CorpusBundleError(f"bundle not found: {bundle_path}")
    size = bundle_path.stat().st_size
    if size > max_bytes:
        raise CorpusBundleError(f"bundle exceeds max_bundle_bytes ({size} > {max_bytes})")
    return tarfile.open(bundle_path, mode="r:gz")


def _safe_members(tf: tarfile.TarFile, max_member_bytes: int) -> dict[str, tarfile.TarInfo]:
    """Validate every archive member before anything is read: no absolute paths or
    ``..`` traversal, no symlinks/devices/etc., only the fixed bundle layout, and a
    per-member size cap (defence against a decompression bomb)."""
    out: dict[str, tarfile.TarInfo] = {}
    for m in tf.getmembers():
        name = m.name
        if name.startswith("/") or ".." in Path(name).parts:
            raise CorpusBundleError(f"unsafe path in bundle archive: {name!r}")
        if not m.isfile():
            raise CorpusBundleError(f"non-regular-file member in bundle archive: {name!r}")
        if m.size > max_member_bytes:
            raise CorpusBundleError(f"oversized member in bundle archive: {name!r}")
        if name != MANIFEST_NAME and not name.startswith(ALLOWED_MEMBER_PREFIXES):
            raise CorpusBundleError(f"member outside the allowed bundle layout: {name!r}")
        out[name] = m
    return out


def _lookup_publisher(
    publisher_id: str, trusted_publishers: list[TrustedPublisher]
) -> TrustedPublisher:
    for t in trusted_publishers:
        if t.id == publisher_id:
            return t
    raise CorpusBundleError(
        f"publisher {publisher_id!r} is not in corpus_registry.trusted_publishers; "
        "an operator must add it there before this bundle can install"
    )


def _check_license_allowlist(manifest: BundleManifest, allowlist: list[str]) -> None:
    used = {manifest.license, *(d.license for d in manifest.documents)}
    disallowed = sorted(used - set(allowlist))
    if disallowed:
        raise CorpusBundleError(
            f"license(s) not in corpus_registry.license_allowlist: {disallowed}"
        )


def _check_integrity_tree(
    tf: tarfile.TarFile, members: dict[str, tarfile.TarInfo], manifest: BundleManifest
) -> None:
    expected = dict(manifest.file_hashes)
    content_members = {
        name: m
        for name, m in members.items()
        if name != MANIFEST_NAME and not name.startswith("signature/")
    }
    for name, member in content_members.items():
        digest = expected.get(name)
        if digest is None:
            raise CorpusBundleError(f"bundle file not declared in manifest file_hashes: {name!r}")
        actual = sha256_of_bytes(_read(tf, member))
        if actual != digest:
            raise CorpusBundleError(f"content hash mismatch for {name!r}: bundle may be tampered")
    missing = sorted(set(expected) - set(content_members))
    if missing:
        raise CorpusBundleError(f"manifest declares files missing from the archive: {missing}")

    declared = {d.file for d in manifest.documents} | set(manifest.suites)
    if manifest.toxicity_table:
        declared.add(manifest.toxicity_table)
    orphaned = sorted(declared - set(expected))
    if orphaned:
        raise CorpusBundleError(f"manifest references files with no hash entry: {orphaned}")


def verify_bundle(bundle_path: str | Path, config: Config) -> VerificationReport:
    """Verify signature, publisher trust, license allowlist, and manifest/content
    integrity. Raises ``CorpusBundleError``/``SignatureError`` on the first problem."""
    reg = config.corpus_registry
    path = Path(bundle_path)
    with _open_bundle(path, reg.max_bundle_bytes) as tf:
        members = _safe_members(tf, reg.max_bundle_bytes)
        if MANIFEST_NAME not in members:
            raise CorpusBundleError("bundle is missing manifest.yaml")
        manifest_bytes = _read(tf, members[MANIFEST_NAME])
        manifest = parse_manifest(manifest_bytes)

        trusted = _lookup_publisher(manifest.publisher.id, reg.trusted_publishers)
        sig_name = _SIGNATURE_MEMBER[trusted.signing_scheme]
        if sig_name not in members:
            raise CorpusBundleError(
                f"bundle has no {trusted.signing_scheme} signature file "
                f"({sig_name!r}) for publisher {trusted.id!r}"
            )
        signature_bytes = _read(tf, members[sig_name])
        signature = verify_signature(
            manifest_bytes,
            scheme=trusted.signing_scheme,
            signature_bytes=signature_bytes,
            trusted=trusted,
        )

        _check_license_allowlist(manifest, reg.license_allowlist)
        _check_integrity_tree(tf, members, manifest)

    return VerificationReport(manifest=manifest, manifest_bytes=manifest_bytes, signature=signature)


def install_bundle(
    bundle_path: str | Path, config: Config, *, dest_root: str | Path | None = None
) -> InstalledCorpus:
    """Verify, then extract into the registry namespace and record provenance.

    Never touches ``corpus.path``/``corpus.manifest`` or ``config/`` — this is a
    separate namespace by construction, not by convention.
    """
    report = verify_bundle(bundle_path, config)
    manifest = report.manifest
    reg = config.corpus_registry
    root = Path(dest_root) if dest_root is not None else Path(reg.registry_path)
    install_dir = root / manifest.publisher.id / manifest.name / manifest.version
    if install_dir.exists():
        shutil.rmtree(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)

    with _open_bundle(Path(bundle_path), reg.max_bundle_bytes) as tf:
        members = _safe_members(tf, reg.max_bundle_bytes)
        for name, member in members.items():
            if name.startswith("signature/"):
                continue  # the signature is not corpus content; provenance below covers it
            target = install_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_read(tf, member))

    provenance = {
        "schema_version": "1.0",
        "publisher": manifest.publisher.model_dump(),
        "bundle_name": manifest.name,
        "bundle_version": manifest.version,
        "bundle_license": manifest.license,
        "manifest_sha256": sha256_of_bytes(report.manifest_bytes),
        "signing_scheme": report.signature.scheme,
        "signing_identity": report.signature.identity,
        "installed_at": datetime.now(UTC).isoformat(),
    }
    provenance_path = install_dir / "PROVENANCE.json"
    provenance_json = json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    provenance_path.write_text(provenance_json, encoding="utf-8")

    return InstalledCorpus(
        publisher_id=manifest.publisher.id,
        name=manifest.name,
        version=manifest.version,
        install_path=install_dir,
        provenance_path=provenance_path,
    )
