"""E3: build the shared golden eval set used by every tool in the comparison.

This is NOT a new eval set. It replays sprout's real `sprout.answer.Assistant` over the
real, committed `eval/suites/*.yaml` cases exactly the way `sprout eval` / `record.py`
does, using the same config the CI eval gate uses (config/sprout.yaml, offline
deterministic embedder + extractive generator, no network/API key). It then reshapes the
*same* underlying (question, answer, citations) triples into the input formats Ragas,
DeepEval, and an ALCE-style citation P/R scorer expect, and also recomputes the in-house
`GroundednessSuite` per-item score so every tool is scored against literally the same
generated answers.

Run from the repo root with the project's own venv (needs `sprout` importable):
    uv run python eval/research/e3_external_suite_comparison/build_golden_set.py \
        --out eval/research/e3_external_suite_comparison/golden_set.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sprout.answer import Assistant
from sprout.config import load_config
from sprout.eval.dataset import load_suite_dir
from sprout.eval.judge import DeterministicJudge
from sprout.eval.suites._common import claims as split_claims
from sprout.eval.record import record

PER_ITEM_THRESHOLD = 0.8  # mirrors GroundednessSuite.PER_ITEM_THRESHOLD


def in_house_groundedness_item(judge: DeterministicJudge, text: str, sources: list[str]) -> dict:
    """Exact replay of GroundednessSuite.run's per-item loop (suites/groundedness.py)."""
    item_claims = split_claims(text)
    if not item_claims:
        return {"claims": [], "entailed": 0, "ratio": 0.0, "passed": False, "detail": "no claims"}
    entailed = 0
    worst = ""
    claim_detail = []
    for claim in item_claims:
        decision = judge.entails(claim, sources)
        claim_detail.append(
            {"claim": claim, "passed": decision.passed, "score": decision.score, "detail": decision.detail}
        )
        if decision.passed:
            entailed += 1
        elif not worst:
            worst = f"{claim!r}: {decision.detail}"
    ratio = entailed / len(item_claims)
    return {
        "claims": claim_detail,
        "entailed": entailed,
        "ratio": round(ratio, 4),
        "passed": ratio >= PER_ITEM_THRESHOLD,
        "detail": worst or "all claims entailed",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/sprout.yaml")
    ap.add_argument("--suite-dir", default="eval/suites")
    ap.add_argument("--out", default="eval/research/e3_external_suite_comparison/golden_set.json")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    assistant = Assistant.from_config(cfg)

    dataset = load_suite_dir(args.suite_dir)
    golden = record(assistant, dataset, cfg)  # same call `sprout eval` makes

    judge = DeterministicJudge()

    records = []
    for item in golden.items:
        tr = item.target_response
        applicable = (
            tr is not None
            and not tr.refused
            and bool(item.sources)
            and bool(tr.text)
        )
        # Recompute the *full* Answer so we can also capture the raw retrieved set
        # (not just the cited quotes `record.py` keeps in `item.sources`) — needed for
        # Ragas/ALCE context-precision-style scoring, which wants "what was retrieved"
        # as well as "what was actually cited".
        ans = assistant.answer(item.question, item.language)
        retrieved_contexts = [
            {"text": rc.chunk.text, "score": rc.score, "source": rc.chunk.source}
            for rc in ans.retrieved
        ]
        cited = [
            {"quote": c.quote, "label": c.label, "source": c.source} for c in ans.citations
        ]
        # Per-sentence citation mapping (sprout's citation_guard attaches exactly one
        # citation per rendered sentence) — this is the natural unit for an ALCE-style
        # statement-level citation precision/recall metric, distinct from the item-level
        # `cited_quotes` list the in-house GroundednessSuite checks claims against.
        sentence_citations = [
            {"text": s.text, "citation_quote": s.citation.quote, "citation_label": s.citation.label}
            for s in ans.sentences
        ]

        rec = {
            "id": item.id,
            "suite_origin": item.id.split("-")[0],
            "question": item.question,
            "language": item.language,
            "expected_behavior": item.expected_behavior,
            "expected_facts": item.expected_facts,
            "applicable_to_groundedness": applicable,
            "answer_text": tr.text if tr else "",
            "refused": tr.refused if tr else True,
            "confidence": tr.confidence if tr else None,
            "cited_quotes": item.sources,  # = [c.quote for c in ans.citations], per record.py
            "citations": cited,
            "sentence_citations": sentence_citations,
            "retrieved_contexts": retrieved_contexts,
        }
        if applicable:
            rec["in_house_groundedness"] = in_house_groundedness_item(judge, tr.text, item.sources)
        records.append(rec)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"dataset_version": golden.version, "items": records}, indent=2))

    n_applicable = sum(1 for r in records if r["applicable_to_groundedness"])
    n_pass = sum(
        1 for r in records if r["applicable_to_groundedness"] and r["in_house_groundedness"]["passed"]
    )
    print(f"wrote {len(records)} items ({n_applicable} applicable to groundedness) -> {out_path}")
    print(f"in-house groundedness (replayed): {n_pass}/{n_applicable} = {n_pass / n_applicable:.4f}")


if __name__ == "__main__":
    main()
