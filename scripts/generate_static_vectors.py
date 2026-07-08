"""Regenerate ``static_vectors.json`` from ``clusters.yaml`` (EXP-03, ADR-0013).

Deterministic, offline, dependency-free. Every cluster in ``clusters.yaml`` groups
English and Spanish synonyms/paraphrases of one plant-care concept; this script:

1. Derives one 64-dimensional seed vector per cluster from a SHA-256 hash of the
   cluster's name (stable across runs and machines — no ``random`` module seeding,
   which is not guaranteed stable across Python versions).
2. Tokenizes every term in the cluster with the *same* ``content_tokens()`` pipeline
   retrieval and grounding use, so lookups at query time hit the same keys.
3. Assigns each resulting token the L2-normalised sum of the seed vectors of every
   cluster it appears in (a token that legitimately belongs to more than one concept
   lands between them rather than arbitrarily picking one).

Run ``uv run python scripts/generate_static_vectors.py`` after editing
``clusters.yaml``; the output is committed, so this script is a build step, not a
runtime dependency (mirrors ``make ingest`` regenerating the index from source data).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from sprout.text import content_tokens

DIM = 64
ROOT = Path(__file__).resolve().parent.parent
CLUSTERS_PATH = ROOT / "src" / "sprout" / "data" / "embeddings" / "clusters.yaml"
OUTPUT_PATH = ROOT / "src" / "sprout" / "data" / "embeddings" / "static_vectors.json"


def _seed_vector(name: str, dim: int = DIM) -> list[float]:
    """A deterministic, roughly-uniform unit vector derived from ``name``.

    Repeated SHA-256 hashing of ``name || counter`` is used as a stable byte stream
    (not for cryptographic strength) so the vector is byte-identical across machines
    and Python versions, unlike ``random.Random(seed)`` whose stream is not part of
    Python's compatibility guarantees.
    """
    vec: list[float] = []
    counter = 0
    while len(vec) < dim:
        digest = hashlib.sha256(f"{name}::{counter}".encode()).digest()
        for i in range(0, len(digest) - 1, 2):
            if len(vec) >= dim:
                break
            # Map a 16-bit unsigned chunk to [-1, 1).
            raw = int.from_bytes(digest[i : i + 2], "big")
            vec.append((raw / 32768.0) - 1.0)
        counter += 1
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm else vec


def _add(a: list[float], b: list[float]) -> list[float]:
    return [x + y for x, y in zip(a, b, strict=True)]


def _normalize(vec: list[float]) -> list[float]:
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm else vec


def build_table() -> dict[str, object]:
    raw = yaml.safe_load(CLUSTERS_PATH.read_text(encoding="utf-8"))
    clusters: dict[str, list[str]] = raw["clusters"]

    cluster_vectors = {name: _seed_vector(name) for name in clusters}

    token_accum: dict[str, list[float]] = {}
    for name, terms in clusters.items():
        cvec = cluster_vectors[name]
        for term in terms:
            for token in content_tokens(term):
                if token in token_accum:
                    token_accum[token] = _add(token_accum[token], cvec)
                else:
                    token_accum[token] = list(cvec)

    vectors = {token: _normalize(vec) for token, vec in sorted(token_accum.items())}
    return {
        "dim": DIM,
        "source": "clusters.yaml",
        "generator": "scripts/generate_static_vectors.py",
        "n_terms": sum(len(terms) for terms in clusters.values()),
        "n_tokens": len(vectors),
        "vectors": vectors,
    }


def main() -> None:
    table = build_table()
    OUTPUT_PATH.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT_PATH} ({table['n_tokens']} tokens from {table['n_terms']} terms)")


if __name__ == "__main__":
    main()
