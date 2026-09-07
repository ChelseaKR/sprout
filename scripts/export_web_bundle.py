"""Export the static assets the browser-native TypeScript port (``web-static/``) needs.

EXP-08 (docs/ideation/03-expansions.md) ports the deterministic pipeline — hashing
embedder, BM25, extractive generator, guards — to TypeScript so the assistant can run as
a zero-server static site. The *algorithms* are reimplemented in TypeScript (see
``web-static/src``), but the *data* they run on (the vector/BM25 index and the
guards/prompts/retrieval configuration: deny-lists, toxicity keywords, species aliases,
per-language prompt strings) must stay byte-identical to the Python side, or the two
implementations drift. Rather than hand-copy that data into TypeScript source (which
would silently rot the next time ``config/sprout.yaml`` changes), this script dumps it
straight from the loaded, validated :class:`~sprout.config.Config` to JSON, and copies
the built index alongside it. Both files are plain static assets fetched by the PWA at
runtime — no server, no build-time secret.

The bundle also records *which* corpus and *which* configuration it was built from, so a
deployed bundle can be asked whether it is still the one this checkout describes. That
lives in :mod:`sprout.web_bundle`, which both writes it here and re-derives it in
``sprout bundle-check``; this file is deliberately a thin entry point so the exported
shape has exactly one definition.

Usage: ``uv run python scripts/export_web_bundle.py [--config config/sprout.yaml]``
(run after ``make ingest`` so ``var/index.json`` exists).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sprout.web_bundle import WebBundleError, export_bundle

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config" / "sprout.yaml"))
    parser.add_argument("--index", default=str(ROOT / "var" / "index.json"))
    parser.add_argument("--out", default=str(ROOT / "web-static" / "public" / "data"))
    args = parser.parse_args()

    try:
        config_dest, index_dest = export_bundle(args.config, args.index, args.out)
    except WebBundleError as exc:
        raise SystemExit(f"export_web_bundle: {exc}") from exc
    print(f"Wrote {config_dest}")
    print(f"Wrote {index_dest}")


if __name__ == "__main__":
    main()
