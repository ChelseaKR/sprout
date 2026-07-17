"""Generate the cross-language conformance fixtures for the TypeScript port (EXP-08).

For every case in ``eval/suites/*.yaml`` (the same question set the Python eval harness
scores against), run the real Python :class:`~sprout.answer.Assistant` and record its
answer. ``web-static/test/conformance.test.ts`` replays every question through the
TypeScript port and asserts byte-identical output — this fixture file *is* the
conformance test's spine (per the ideation shape: "dual-implementation drift is the big
one — the conformance test is the deliverable's spine").

Usage: ``uv run python scripts/generate_conformance_fixtures.py`` (run after
``make ingest``). Writes ``web-static/test/fixtures/conformance.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sprout.answer import Assistant
from sprout.config import load_config
from sprout.store import VectorStore

ROOT = Path(__file__).resolve().parent.parent
SUITE_DIR = ROOT / "eval" / "suites"
OUT_PATH = ROOT / "web-static" / "test" / "fixtures" / "conformance.json"


def _load_questions() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for suite_path in sorted(SUITE_DIR.glob("*.yaml")):
        data = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
        for case in data.get("cases", []):
            case_id = case["id"]
            if case_id in seen_ids:
                # A handful of cases are intentionally duplicated across suites (e.g. a
                # safety case mirrored into refusal); keep the fixture set to one entry
                # per unique question+language pair.
                continue
            seen_ids.add(case_id)
            cases.append(
                {
                    "id": case_id,
                    "question": case["question"],
                    "language": case.get("language", "en"),
                    "suite": suite_path.stem,
                }
            )
    return cases


def main() -> None:
    cfg = load_config(ROOT / "config" / "sprout.yaml")
    store = VectorStore.load(cfg.store.path)
    assistant = Assistant.from_store(cfg, store)

    fixtures = []
    for case in _load_questions():
        answer = assistant.answer(case["question"], language=case["language"])
        fixtures.append(
            {
                "id": case["id"],
                "suite": case["suite"],
                "question": case["question"],
                "language_requested": case["language"],
                "expected": {
                    "language": answer.language,
                    "refused": answer.refused,
                    "refusal_reason": answer.refusal_reason,
                    "text": answer.text,
                    "display_text": answer.display_text,
                    "citations": [c.chunk_id for c in answer.citations],
                    "confidence": answer.confidence,
                    "low_confidence": answer.low_confidence,
                    "abstained": answer.abstained,
                    "is_safety_query": answer.is_safety_query,
                    "safety_notice": answer.safety_notice,
                    "disclosure": answer.disclosure,
                    "as_of": answer.as_of,
                },
            }
        )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(
            {"format_version": 1, "cases": fixtures}, ensure_ascii=False, sort_keys=True, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(fixtures)} fixture cases to {OUT_PATH}")


if __name__ == "__main__":
    main()
