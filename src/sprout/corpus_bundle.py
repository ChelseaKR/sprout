"""The signed corpus bundle format (EXP-15, ``docs/ideation/03-expansions.md``).

A bundle is a gzipped tar archive a third-party publisher hands to ``sprout corpus
verify|install``:

```
manifest.yaml       # BundleManifest below — the ONLY file trusted for provenance/paths
signature/           # a detached signature over manifest.yaml's canonical bytes
  sigstore.json       #   a real Sigstore bundle (cosign/`sigstore sign --bundle`), or
  dev.sig              #   a raw Ed25519 signature, dev/test publishers only
processed/*.md        # passages, same shape as corpus/processed/*.md
toxicity.yaml         # optional toxicity table
suites/*.yaml          # optional eval cases
```

``manifest.yaml`` carries a ``file_hashes`` map (relative path -> sha256) covering every
other file in the archive, so the single signature over the manifest transitively covers
the whole bundle (the "sha256 tree" from the ideation shape). ``BundleManifest`` forbids
unknown top-level keys, which is the mechanism — not just a convention — that keeps a
bundle from ever carrying a ``guards``/``config`` section: there is no field for it, so a
bundle attempting to smuggle one fails to parse rather than silently being ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .ingest import ManifestEntry

SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"

# The only path prefixes a bundle archive member may live under. Anything else (an
# absolute path, a ``..`` traversal, or a file like ``config/sprout.yaml``) is rejected
# before extraction — this is what makes an installed bundle structurally unable to
# reach Sprout's own config or source tree.
ALLOWED_MEMBER_PREFIXES = ("manifest.yaml", "signature/", "processed/", "toxicity.yaml", "suites/")


class BundleError(ValueError):
    """A malformed bundle manifest or an integrity-tree mismatch. Fails closed."""


class Publisher(BaseModel):
    """Who claims to have made this bundle. Descriptive only — *not* the trust root.

    Verification never trusts these fields for cryptographic identity; it looks
    ``id`` up in the installer's own ``corpus_registry.trusted_publishers`` config and
    verifies against *that* entry's signing scheme/identity/issuer.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str
    contact: str


class BundleManifest(BaseModel):
    """The one file a signature covers; the source of truth for a bundle's contents."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    publisher: Publisher
    license: str
    created: str  # ISO-8601 date
    documents: tuple[ManifestEntry, ...] = Field(min_length=1)
    toxicity_table: str | None = None
    suites: tuple[str, ...] = ()
    file_hashes: dict[str, str]  # relative path (as in the tar) -> sha256 hex digest
    notes: str = ""

    @field_validator("documents")
    @classmethod
    def _documents_under_processed(
        cls, docs: tuple[ManifestEntry, ...]
    ) -> tuple[ManifestEntry, ...]:
        for doc in docs:
            _require_safe_relpath(doc.file, prefix="processed/")
        return docs

    @field_validator("toxicity_table")
    @classmethod
    def _toxicity_table_path(cls, value: str | None) -> str | None:
        if value is not None:
            _require_safe_relpath(value, prefix=None)
        return value

    @field_validator("suites")
    @classmethod
    def _suites_under_suites(cls, paths: tuple[str, ...]) -> tuple[str, ...]:
        for p in paths:
            _require_safe_relpath(p, prefix="suites/")
        return paths

    @field_validator("file_hashes")
    @classmethod
    def _file_hashes_safe(cls, hashes: dict[str, str]) -> dict[str, str]:
        for rel in hashes:
            _require_safe_relpath(rel, prefix=None)
        return hashes


def _require_safe_relpath(rel: str, *, prefix: str | None) -> None:
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        raise ValueError(f"unsafe path in bundle manifest: {rel!r}")
    if not rel.startswith(ALLOWED_MEMBER_PREFIXES):
        raise ValueError(f"path outside the allowed bundle layout: {rel!r}")
    if prefix is not None and not rel.startswith(prefix):
        raise ValueError(f"expected {rel!r} to live under {prefix!r}")


def parse_manifest(raw_yaml_bytes: bytes) -> BundleManifest:
    """Parse and validate ``manifest.yaml`` bytes. Raises ``BundleError`` on any problem.

    A YAML mapping with an unrecognised top-level key (``guards``, ``config``,
    ``routing``, or anything else not in ``BundleManifest``) fails here, by
    construction — that is the enforcement, not a denylist of bad keys.
    """
    import yaml

    try:
        raw = yaml.safe_load(raw_yaml_bytes)
        if not isinstance(raw, dict):
            raise BundleError("manifest.yaml must be a YAML mapping")
        return BundleManifest.model_validate(raw)
    except BundleError:
        raise
    except Exception as exc:  # pydantic ValidationError, yaml errors, etc.
        raise BundleError(f"invalid bundle manifest: {exc}") from exc
