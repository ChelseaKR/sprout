"""``sprout corpus verify|install`` via the CLI (EXP-15)."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from typer.testing import CliRunner

from sprout.cli import app
from sprout.determinism import sha256_of_bytes

runner = CliRunner()

DOC_REL = "processed/sample.md"
DOC_TEXT = "Sample care passage text.\n"


def _add(tf: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))


def _build_bundle(tmp_path: Path, key: Ed25519PrivateKey, *, license_: str = "CC0-1.0") -> Path:
    doc_bytes = DOC_TEXT.encode("utf-8")
    manifest_dict = {
        "schema_version": "1.0",
        "name": "acme-tropicals",
        "version": "1.0.0",
        "publisher": {
            "id": "acme-botanicals",
            "name": "Acme Botanicals",
            "contact": "hi@acme.example",
        },
        "license": license_,
        "created": "2026-07-08",
        "documents": [
            {
                "file": DOC_REL,
                "title": "Sample",
                "source_name": "Acme",
                "url": "https://acme.example/sample",
                "license": license_,
                "fetch_date": "2026-07-01",
                "language": "en",
                "topic": "care",
            }
        ],
        "file_hashes": {DOC_REL: sha256_of_bytes(doc_bytes)},
    }
    manifest_bytes = yaml.safe_dump(manifest_dict).encode("utf-8")
    signature_bytes = key.sign(manifest_bytes)
    bundle_path = tmp_path / "bundle.sproutcorpus"
    with tarfile.open(bundle_path, "w:gz") as tf:
        _add(tf, "manifest.yaml", manifest_bytes)
        _add(tf, "signature/dev.sig", signature_bytes)
        _add(tf, DOC_REL, doc_bytes)
    return bundle_path


def _write_config(tmp_path: Path, key: Ed25519PrivateKey) -> Path:
    pub_hex = key.public_key().public_bytes_raw().hex()
    cfg = {
        "corpus_registry": {
            "registry_path": str(tmp_path / "registry"),
            "license_allowlist": ["CC0-1.0"],
            "trusted_publishers": [
                {
                    "id": "acme-botanicals",
                    "name": "Acme Botanicals",
                    "signing_scheme": "dev-ed25519",
                    "identity": pub_hex,
                }
            ],
        }
    }
    cfg_path = tmp_path / "sprout.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return cfg_path


def test_corpus_verify_ok(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    bundle = _build_bundle(tmp_path, key)
    cfg = _write_config(tmp_path, key)
    result = runner.invoke(app, ["corpus", "verify", str(bundle), "--config", str(cfg)])
    assert result.exit_code == 0, result.stdout
    assert "OK" in result.stdout
    assert "acme-tropicals" in result.stdout


def test_corpus_verify_rejects_bad_license(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    bundle = _build_bundle(tmp_path, key, license_="Proprietary")
    cfg = _write_config(tmp_path, key)
    result = runner.invoke(app, ["corpus", "verify", str(bundle), "--config", str(cfg)])
    assert result.exit_code == 1
    assert "REJECTED" in result.output


def test_corpus_install_writes_registry_and_provenance(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    bundle = _build_bundle(tmp_path, key)
    cfg = _write_config(tmp_path, key)
    result = runner.invoke(app, ["corpus", "install", str(bundle), "--config", str(cfg)])
    assert result.exit_code == 0, result.stdout
    assert "Installed acme-tropicals" in result.stdout
    install_dir = tmp_path / "registry" / "acme-botanicals" / "acme-tropicals" / "1.0.0"
    assert (install_dir / DOC_REL).exists()
    assert (install_dir / "PROVENANCE.json").exists()


def test_corpus_install_rejects_unsigned(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    other_key = Ed25519PrivateKey.generate()
    bundle = _build_bundle(tmp_path, key)
    cfg = _write_config(tmp_path, other_key)  # config trusts a different key
    result = runner.invoke(app, ["corpus", "install", str(bundle), "--config", str(cfg)])
    assert result.exit_code == 1
    assert "REJECTED" in result.output
    assert not (tmp_path / "registry").exists()
