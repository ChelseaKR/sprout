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

Usage: ``uv run python scripts/export_web_bundle.py [--config config/sprout.yaml]``
(run after ``make ingest`` so ``var/index.json`` exists).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from sprout.config import load_config

ROOT = Path(__file__).resolve().parent.parent


def _export_config(config_path: Path, out_dir: Path) -> Path:
    cfg = load_config(config_path)
    if cfg.retrieval.embedding_provider != "deterministic":
        raise SystemExit(
            "export_web_bundle: retrieval.embedding_provider must be 'deterministic' — "
            "the browser port only implements the offline hashing embedder."
        )
    bundle = {
        "format_version": 1,
        "retrieval": {
            "top_k": cfg.retrieval.top_k,
            "min_score": cfg.retrieval.min_score,
            "embedding_dim": cfg.retrieval.embedding_dim,
            "hybrid": cfg.retrieval.hybrid,
            "bm25_k1": cfg.retrieval.bm25_k1,
            "bm25_b": cfg.retrieval.bm25_b,
            "rrf_k": cfg.retrieval.rrf_k,
            "dedup_threshold": cfg.retrieval.dedup_threshold,
            "topic_filter": cfg.retrieval.topic_filter,
            "species_aliases": cfg.retrieval.species_aliases,
        },
        "generation": {
            "max_sentences": cfg.generation.max_sentences,
            "relevance_floor": cfg.generation.relevance_floor,
            "support_overlap": cfg.generation.support_overlap,
        },
        "confidence": {
            "abstain_threshold": cfg.confidence.abstain_threshold,
            "low_confidence_threshold": cfg.confidence.low_confidence_threshold,
            # The logistic's shape, when `sprout fit-confidence` (ADR-0016) has written
            # one. Python reads it in `confidence.py::_constants`; without it here the
            # browser would keep using the ADR-0012 defaults and compute a different
            # confidence — and therefore different abstain/low-confidence decisions —
            # than the CLI for the same question, silently, from the first committed
            # fit onward (issue #108). `null` when no fit is committed, which is what
            # tells the TypeScript side to use the same defaults Python would.
            "fit": (
                None
                if cfg.confidence.fit is None
                else {
                    "midpoint": cfg.confidence.fit.midpoint,
                    "steepness": cfg.confidence.fit.steepness,
                    "margin_bonus": cfg.confidence.fit.margin_bonus,
                }
            ),
        },
        "guards": {
            "forbidden_safe_phrases": cfg.guards.forbidden_safe_phrases,
            "toxicity_keywords": cfg.guards.toxicity_keywords,
            "route_terms": cfg.guards.route_terms,
        },
        "languages": {
            "supported": cfg.languages.supported,
            "default": cfg.corpus.default_language,
        },
        "prompts": {
            "refusal_by_lang": cfg.prompts.refusal_by_lang,
            "disclosure_by_lang": cfg.prompts.disclosure_by_lang,
            "safety_route_by_lang": cfg.prompts.safety_route_by_lang,
            "nontoxic_caveat_by_lang": cfg.prompts.nontoxic_caveat_by_lang,
            "escalation_card_by_lang": cfg.prompts.escalation_card_by_lang,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "config.json"
    dest.write_text(
        json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return dest


def _copy_index(index_path: Path, out_dir: Path) -> Path:
    if not index_path.exists():
        raise SystemExit(f"export_web_bundle: {index_path} not found — run `make ingest` first.")
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "index.json"
    shutil.copyfile(index_path, dest)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config" / "sprout.yaml"))
    parser.add_argument("--index", default=str(ROOT / "var" / "index.json"))
    parser.add_argument("--out", default=str(ROOT / "web-static" / "public" / "data"))
    args = parser.parse_args()

    out_dir = Path(args.out)
    config_dest = _export_config(Path(args.config), out_dir)
    index_dest = _copy_index(Path(args.index), out_dir)
    print(f"Wrote {config_dest}")
    print(f"Wrote {index_dest}")


if __name__ == "__main__":
    main()
