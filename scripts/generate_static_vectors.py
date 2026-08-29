"""Regenerate ``static_vectors.json`` from ``clusters.yaml`` (EXP-03, ADR-0017).

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

``--check`` renders the table and compares it against the committed file without
writing anything, so a ``clusters.yaml`` edit that was never regenerated fails a gate
instead of shipping a stale table. ``tests/test_committed_artifacts_are_current.py``
runs it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
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


def render() -> str:
    """The exact bytes ``main()`` writes. One serialiser, so ``--check`` cannot drift
    from the writer it is checking."""
    return json.dumps(build_table(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; exit non-zero if the committed table is not what this "
        "generator now produces from clusters.yaml.",
    )
    args = parser.parse_args(argv)
    rendered = render()

    if args.check:
        # Deliberately never writes. A gate that regenerates into the working tree heals
        # its own drift locally and leaves the committed bytes stale, which is the exact
        # failure this check exists to catch.
        if not OUTPUT_PATH.exists():
            print(f"{OUTPUT_PATH} is missing; run `python {Path(__file__).name}`", file=sys.stderr)
            return 1
        committed = OUTPUT_PATH.read_text(encoding="utf-8")
        if committed != rendered:
            print(
                f"{OUTPUT_PATH} is stale: clusters.yaml (or this generator) changed since it "
                f"was last regenerated. Run `uv run python scripts/{Path(__file__).name}` "
                "and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT_PATH} is current")
        return 0

    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    table = json.loads(rendered)
    print(f"wrote {OUTPUT_PATH} ({table['n_tokens']} tokens from {table['n_terms']} terms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
