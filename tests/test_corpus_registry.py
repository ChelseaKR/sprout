"""``sprout corpus verify|install`` end to end (EXP-15), fully offline via dev-ed25519.

Builds real ``.sproutcorpus`` tarballs in-memory/on-disk and signs them with a real
Ed25519 keypair (the ``dev-ed25519`` scheme — see ``corpus_signing.py`` for why that
scheme, not ``sigstore-keyless``, is what CI exercises end to end). Every failure mode
in the shape ("unsigned or tampered bundle is unloadable by construction") gets its own
test: tampered content, tampered manifest, untrusted publisher, disallowed license, and
archive path traversal.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sprout.config import Config
from sprout.corpus_bundle import BundleError
from sprout.corpus_registry import CorpusBundleError, InstalledCorpus, install_bundle, verify_bundle
from sprout.corpus_signing import SignatureError
from sprout.determinism import sha256_of_bytes

DOC_REL = "processed/sample.md"
DOC_TEXT = "Sample care passage text.\n"


def _add(tf: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))


def build_bundle(
    tmp_path: Path,
    *,
    key: Ed25519PrivateKey,
    publisher_id: str = "acme-botanicals",
    name: str = "acme-tropicals",
    version: str = "1.0.0",
    license_: str = "CC0-1.0",
    doc_license: str | None = None,
    doc_text: str = DOC_TEXT,
    file_hashes_override: dict[str, str] | None = None,
    extra_manifest_keys: dict[str, object] | None = None,
    extra_members: dict[str, bytes] | None = None,
    skip_signature: bool = False,
    corrupt_signature: bool = False,
    filename: str = "bundle.sproutcorpus",
) -> Path:
    doc_bytes = doc_text.encode("utf-8")
    file_hashes = file_hashes_override or {DOC_REL: sha256_of_bytes(doc_bytes)}
    manifest_dict: dict[str, object] = {
        "schema_version": "1.0",
        "name": name,
        "version": version,
        "publisher": {"id": publisher_id, "name": "Acme Botanicals", "contact": "hi@acme.example"},
        "license": license_,
        "created": "2026-07-08",
        "documents": [
            {
                "file": DOC_REL,
                "title": "Sample",
                "source_name": "Acme",
                "url": "https://acme.example/sample",
                "license": doc_license or license_,
                "fetch_date": "2026-07-01",
                "language": "en",
                "topic": "care",
            }
        ],
        "file_hashes": file_hashes,
    }
    if extra_manifest_keys:
        manifest_dict.update(extra_manifest_keys)
    manifest_bytes = yaml.safe_dump(manifest_dict).encode("utf-8")
    signature_bytes = key.sign(manifest_bytes)
    if corrupt_signature:
        signature_bytes = bytes([signature_bytes[0] ^ 0xFF]) + signature_bytes[1:]

    bundle_path = tmp_path / filename
    with tarfile.open(bundle_path, "w:gz") as tf:
        _add(tf, "manifest.yaml", manifest_bytes)
        if not skip_signature:
            _add(tf, "signature/dev.sig", signature_bytes)
        _add(tf, DOC_REL, doc_bytes)
        for member_name, data in (extra_members or {}).items():
            _add(tf, member_name, data)
    return bundle_path


def make_config(
    tmp_path: Path,
    *,
    publisher_id: str,
    pubkey_hex: str,
    allowlist: list[str] | None = None,
) -> Config:
    return Config.model_validate(
        {
            "corpus_registry": {
                "registry_path": str(tmp_path / "registry"),
                "license_allowlist": allowlist or ["CC0-1.0", "MIT"],
                "trusted_publishers": [
                    {
                        "id": publisher_id,
                        "name": "Acme Botanicals",
                        "signing_scheme": "dev-ed25519",
                        "identity": pubkey_hex,
                    }
                ],
            }
        }
    )


@pytest.fixture
def keypair() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _pub_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes_raw().hex()


def test_verify_valid_bundle_ok(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    bundle = build_bundle(tmp_path, key=keypair)
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    report = verify_bundle(bundle, cfg)
    assert report.manifest.name == "acme-tropicals"
    assert report.signature.scheme == "dev-ed25519"


def test_verify_unsigned_bundle_rejected(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    bundle = build_bundle(tmp_path, key=keypair, skip_signature=True)
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(CorpusBundleError, match="signature file"):
        verify_bundle(bundle, cfg)


def test_verify_corrupted_signature_rejected(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    bundle = build_bundle(tmp_path, key=keypair, corrupt_signature=True)
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(SignatureError):
        verify_bundle(bundle, cfg)


def test_verify_tampered_content_rejected(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    # Signature still verifies (it covers manifest.yaml only) but the declared content
    # hash for the passage no longer matches — the integrity tree must catch this
    # independently of the signature.
    bundle_path = tmp_path / "bundle.sproutcorpus"
    doc_bytes = DOC_TEXT.encode("utf-8")
    file_hashes = {DOC_REL: sha256_of_bytes(doc_bytes)}
    manifest_dict = {
        "schema_version": "1.0",
        "name": "acme-tropicals",
        "version": "1.0.0",
        "publisher": {"id": "acme-botanicals", "name": "Acme", "contact": "hi@acme.example"},
        "license": "CC0-1.0",
        "created": "2026-07-08",
        "documents": [
            {
                "file": DOC_REL,
                "title": "Sample",
                "source_name": "Acme",
                "url": "https://acme.example/sample",
                "license": "CC0-1.0",
                "fetch_date": "2026-07-01",
                "language": "en",
                "topic": "care",
            }
        ],
        "file_hashes": file_hashes,
    }
    manifest_bytes = yaml.safe_dump(manifest_dict).encode("utf-8")
    signature_bytes = keypair.sign(manifest_bytes)
    with tarfile.open(bundle_path, "w:gz") as tf:
        _add(tf, "manifest.yaml", manifest_bytes)
        _add(tf, "signature/dev.sig", signature_bytes)
        _add(tf, DOC_REL, b"TAMPERED CONTENT, not what was signed for\n")

    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(CorpusBundleError, match="content hash mismatch"):
        verify_bundle(bundle_path, cfg)


def test_verify_untrusted_publisher_rejected(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    bundle = build_bundle(tmp_path, key=keypair, publisher_id="stranger")
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(CorpusBundleError, match="not in corpus_registry"):
        verify_bundle(bundle, cfg)


def test_verify_disallowed_license_rejected(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    bundle = build_bundle(tmp_path, key=keypair, license_="Proprietary-NoRedistribute")
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(CorpusBundleError, match="license"):
        verify_bundle(bundle, cfg)


def test_verify_missing_manifest_rejected(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    bundle_path = tmp_path / "no-manifest.sproutcorpus"
    with tarfile.open(bundle_path, "w:gz") as tf:
        _add(tf, "processed/sample.md", b"x")
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(CorpusBundleError, match="missing manifest"):
        verify_bundle(bundle_path, cfg)


def test_verify_path_traversal_member_rejected(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    bundle = build_bundle(tmp_path, key=keypair, extra_members={"../../etc/passwd": b"evil"})
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(CorpusBundleError, match="unsafe path"):
        verify_bundle(bundle, cfg)


def test_verify_member_outside_allowed_layout_rejected(
    tmp_path: Path, keypair: Ed25519PrivateKey
) -> None:
    bundle = build_bundle(
        tmp_path, key=keypair, extra_members={"config/sprout.yaml": b"guards: {}"}
    )
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(CorpusBundleError, match="outside the allowed bundle layout"):
        verify_bundle(bundle, cfg)


def test_verify_undeclared_content_file_rejected(
    tmp_path: Path, keypair: Ed25519PrivateKey
) -> None:
    bundle = build_bundle(
        tmp_path, key=keypair, extra_members={"processed/smuggled.md": b"not in file_hashes"}
    )
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(CorpusBundleError, match="not declared in manifest file_hashes"):
        verify_bundle(bundle, cfg)


def test_verify_oversized_bundle_rejected(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    bundle = build_bundle(tmp_path, key=keypair)
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    cfg = cfg.model_copy(
        update={"corpus_registry": cfg.corpus_registry.model_copy(update={"max_bundle_bytes": 10})}
    )
    with pytest.raises(CorpusBundleError, match="max_bundle_bytes"):
        verify_bundle(bundle, cfg)


def test_verify_bundle_not_found(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(CorpusBundleError, match="bundle not found"):
        verify_bundle(tmp_path / "does-not-exist.sproutcorpus", cfg)


def test_verify_decompression_bomb_member_rejected(
    tmp_path: Path, keypair: Ed25519PrivateKey
) -> None:
    # A highly compressible member (1 MB of zeros -> a few KB on disk) must still be
    # rejected by its *uncompressed* size against max_bundle_bytes, even though the
    # compressed archive on disk is comfortably under the limit.
    bundle = build_bundle(
        tmp_path, key=keypair, extra_members={"processed/bomb.md": b"\x00" * 1_000_000}
    )
    on_disk_size = bundle.stat().st_size
    assert on_disk_size < 500_000  # highly compressible; confirms this is a real bomb test
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    cfg = cfg.model_copy(
        update={
            "corpus_registry": cfg.corpus_registry.model_copy(update={"max_bundle_bytes": 500_000})
        }
    )
    with pytest.raises(CorpusBundleError, match="oversized member"):
        verify_bundle(bundle, cfg)


def test_verify_manifest_declares_missing_content_file(
    tmp_path: Path, keypair: Ed25519PrivateKey
) -> None:
    bundle_path = tmp_path / "bundle.sproutcorpus"
    manifest_dict = {
        "schema_version": "1.0",
        "name": "acme-tropicals",
        "version": "1.0.0",
        "publisher": {"id": "acme-botanicals", "name": "Acme", "contact": "hi@acme.example"},
        "license": "CC0-1.0",
        "created": "2026-07-08",
        "documents": [
            {
                "file": DOC_REL,
                "title": "Sample",
                "source_name": "Acme",
                "url": "https://acme.example/sample",
                "license": "CC0-1.0",
                "fetch_date": "2026-07-01",
                "language": "en",
                "topic": "care",
            }
        ],
        # declares a hash for a file that is never actually included in the archive
        "file_hashes": {DOC_REL: sha256_of_bytes(DOC_TEXT.encode())},
    }
    manifest_bytes = yaml.safe_dump(manifest_dict).encode("utf-8")
    signature_bytes = keypair.sign(manifest_bytes)
    with tarfile.open(bundle_path, "w:gz") as tf:
        _add(tf, "manifest.yaml", manifest_bytes)
        _add(tf, "signature/dev.sig", signature_bytes)
        # no processed/sample.md member at all

    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(CorpusBundleError, match="missing from the archive"):
        verify_bundle(bundle_path, cfg)


def test_corpus_bundle_error_is_a_bundle_error(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    # CLI callers catch corpus_bundle.BundleError as the single "not installable" type.
    assert issubclass(CorpusBundleError, BundleError)


def test_install_places_files_under_registry_namespace_only(
    tmp_path: Path, keypair: Ed25519PrivateKey
) -> None:
    bundle = build_bundle(tmp_path, key=keypair)
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))

    installed = install_bundle(bundle, cfg)

    assert isinstance(installed, InstalledCorpus)
    assert installed.install_path == (
        tmp_path / "registry" / "acme-botanicals" / "acme-tropicals" / "1.0.0"
    )
    assert (installed.install_path / DOC_REL).read_text(encoding="utf-8") == DOC_TEXT
    assert (installed.install_path / "manifest.yaml").exists()
    assert not (installed.install_path / "signature").exists()

    provenance = json.loads(installed.provenance_path.read_text(encoding="utf-8"))
    assert provenance["publisher"]["id"] == "acme-botanicals"
    assert provenance["signing_scheme"] == "dev-ed25519"
    assert provenance["bundle_version"] == "1.0.0"

    # Never touches Sprout's own corpus/config paths.
    assert not (tmp_path / "config").exists()
    assert not (tmp_path / "corpus" / "manifest.yaml").exists()


def test_install_rejects_same_as_verify(tmp_path: Path, keypair: Ed25519PrivateKey) -> None:
    bundle = build_bundle(tmp_path, key=keypair, publisher_id="stranger")
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    with pytest.raises(CorpusBundleError):
        install_bundle(bundle, cfg)
    # nothing was written
    assert not (tmp_path / "registry").exists()


def test_install_overwrites_existing_same_version(
    tmp_path: Path, keypair: Ed25519PrivateKey
) -> None:
    bundle = build_bundle(tmp_path, key=keypair)
    cfg = make_config(tmp_path, publisher_id="acme-botanicals", pubkey_hex=_pub_hex(keypair))
    first = install_bundle(bundle, cfg)
    second = install_bundle(bundle, cfg)
    assert first.install_path == second.install_path
    assert (second.install_path / DOC_REL).exists()
