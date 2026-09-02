"""``BundleManifest`` schema tests (EXP-15): the enforcement is the schema itself.

A manifest with an unrecognised top-level key (``guards``, ``config``, or anything not
declared on ``BundleManifest``) must fail to parse — that is what makes an installed
bundle structurally unable to alter Sprout's own routing/deny-list strings.
"""

from __future__ import annotations

import pytest

from sprout.corpus_bundle import BundleError, parse_manifest

_VALID: dict[str, object] = {
    "schema_version": "1.0",
    "name": "acme-tropicals",
    "version": "1.0.0",
    "publisher": {
        "id": "acme-botanicals",
        "name": "Acme Botanicals",
        "contact": "hello@acme.example",
    },
    "license": "CC0-1.0",
    "created": "2026-07-08",
    "documents": [
        {
            "file": "processed/sample.md",
            "title": "Sample",
            "source_name": "Acme",
            "url": "https://acme.example/sample",
            "license": "CC0-1.0",
            "fetch_date": "2026-07-01",
            "language": "en",
            "topic": "care",
        }
    ],
    "file_hashes": {"processed/sample.md": "0" * 64},
}


def _dump(obj: dict[str, object]) -> bytes:
    import yaml

    return yaml.safe_dump(obj).encode("utf-8")


def test_valid_manifest_parses() -> None:
    manifest = parse_manifest(_dump(_VALID))
    assert manifest.name == "acme-tropicals"
    assert manifest.publisher.id == "acme-botanicals"
    assert len(manifest.documents) == 1


def test_unknown_top_level_key_rejected() -> None:
    bad = dict(_VALID)
    bad["guards"] = {"forbidden_safe_phrases": {"en": []}}
    with pytest.raises(BundleError):
        parse_manifest(_dump(bad))


def test_config_override_key_rejected() -> None:
    bad = dict(_VALID)
    bad["config_overrides"] = {"generation": {"provider": "bedrock"}}
    with pytest.raises(BundleError):
        parse_manifest(_dump(bad))


def test_document_path_traversal_rejected() -> None:
    bad = dict(_VALID)
    bad["documents"] = [{**_VALID["documents"][0], "file": "../../etc/passwd"}]  # type: ignore[index]
    with pytest.raises(BundleError):
        parse_manifest(_dump(bad))


def test_document_outside_processed_prefix_rejected() -> None:
    bad = dict(_VALID)
    bad["documents"] = [{**_VALID["documents"][0], "file": "config/sprout.yaml"}]  # type: ignore[index]
    with pytest.raises(BundleError):
        parse_manifest(_dump(bad))


def test_suite_path_outside_suites_prefix_rejected() -> None:
    bad = dict(_VALID)
    bad["suites"] = ["processed/not-a-suite.yaml"]
    with pytest.raises(BundleError):
        parse_manifest(_dump(bad))


def test_toxicity_table_path_traversal_rejected() -> None:
    bad = dict(_VALID)
    bad["toxicity_table"] = "../../etc/passwd"
    with pytest.raises(BundleError):
        parse_manifest(_dump(bad))


def test_toxicity_table_valid_path_ok() -> None:
    ok = dict(_VALID)
    ok["toxicity_table"] = "toxicity.yaml"
    manifest = parse_manifest(_dump(ok))
    assert manifest.toxicity_table == "toxicity.yaml"


def test_missing_required_field_rejected() -> None:
    bad = dict(_VALID)
    del bad["publisher"]
    with pytest.raises(BundleError):
        parse_manifest(_dump(bad))


def test_empty_documents_rejected() -> None:
    bad = dict(_VALID)
    bad["documents"] = []
    with pytest.raises(BundleError):
        parse_manifest(_dump(bad))


def test_non_mapping_root_rejected() -> None:
    with pytest.raises(BundleError):
        parse_manifest(b"- just\n- a\n- list\n")


def test_invalid_yaml_rejected() -> None:
    with pytest.raises(BundleError):
        parse_manifest(b"{ not: valid: yaml: [")
