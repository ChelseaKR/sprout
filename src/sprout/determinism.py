"""Content-hashing helpers — the one place all reproducibility funnels through.

Every artifact that must be byte-identical for identical inputs (the corpus index,
the eval dataset, the run fingerprint) is content-addressed here. Hashes are plain
SHA-256 over a *canonical* JSON encoding (sorted keys, compact separators, UTF-8),
so the same logical object always produces the same digest regardless of dict order
or platform. There is deliberately no wall-clock or randomness in this module.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# Fixed seed used across the eval harness; 1729 is the Hardy-Ramanujan number, used
# purely as a memorable constant so reviewers recognise it as "the project seed".
DEFAULT_SEED = 1729


def canonical_bytes(obj: Any) -> bytes:
    """Encode ``obj`` to canonical JSON bytes: sorted keys, compact, UTF-8."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def sha256_of_bytes(data: bytes) -> str:
    """Hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_of_obj(obj: Any) -> str:
    """Hex SHA-256 of any JSON-serialisable object via its canonical encoding."""
    return sha256_of_bytes(canonical_bytes(obj))


def sha256_of_text(text: str) -> str:
    """Hex SHA-256 of a UTF-8 string."""
    return sha256_of_bytes(text.encode("utf-8"))


def sha256_of_file(path: str | Path) -> str:
    """Hex SHA-256 of a file's bytes, read in chunks so large files stream."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def short(digest: str, length: int = 12) -> str:
    """First ``length`` characters of a hex digest, for human-facing version tags."""
    return digest[:length]
