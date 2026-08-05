"""E3: run DeepEval over sprout's real golden eval set (golden_set.json).

Like Ragas, DeepEval's flagship metrics (Faithfulness, ContextualPrecision,
ContextualRecall, AnswerRelevancy) are LLM-judged. Sprout's own CI eval gate is
explicitly offline/zero-API-cost (ADR-0006, ADR-0009) and this environment has no
OpenAI/Anthropic key configured, so this script points DeepEval at DeepEval's own
built-in local-Ollama model support (`deepeval.models.llms.ollama_model.OllamaModel`,
localhost:11434, no network egress beyond that) using the same `qwen2.5:3b` model used
for the Ragas LLM-tier run, for a like-for-like comparison between the two frameworks
under the same judge model. As with Ragas, treat these as directionally informative —
DeepEval's published examples assume a GPT-4-class judge, not a 3B local model.

Usage (inside .venv-ext):
    .venv-ext/bin/python eval/research/e3_external_suite_comparison/run_deepeval.py \
        --golden eval/research/e3_external_suite_comparison/golden_set.json \
        --out eval/research/e3_external_suite_comparison/deepeval_results.json \
        [--limit N]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="eval/research/e3_external_suite_comparison/golden_set.json")
    ap.add_argument("--out", default="eval/research/e3_external_suite_comparison/deepeval_results.json")
    ap.add_argument("--model", default="qwen2.5:3b")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        FaithfulnessMetric,
    )
    from deepeval.models.llms.ollama_model import OllamaModel
    from deepeval.test_case import LLMTestCase

    data = json.loads(Path(args.golden).read_text())
    items = [r for r in data["items"] if r["applicable_to_groundedness"]]
    if args.limit:
        items = items[: args.limit]

    judge = OllamaModel(model=args.model, temperature=0)

    metrics = {
        "faithfulness": FaithfulnessMetric(model=judge, include_reason=False, async_mode=False),
        "contextual_precision": ContextualPrecisionMetric(model=judge, include_reason=False, async_mode=False),
        "contextual_recall": ContextualRecallMetric(model=judge, include_reason=False, async_mode=False),
        "answer_relevancy": AnswerRelevancyMetric(model=judge, include_reason=False, async_mode=False),
    }

    per_item = []
    for n, r in enumerate(items, 1):
        retrieved = [c["text"] for c in r["retrieved_contexts"]]
        expected = " ".join(r["expected_facts"]) or r["answer_text"]
        tc = LLMTestCase(
            input=r["question"],
            actual_output=r["answer_text"],
            retrieval_context=retrieved,
            expected_output=expected,
            context=retrieved,
        )
        row = {"id": r["id"]}
        for name, metric in metrics.items():
            try:
                metric.measure(tc)
                row[name] = metric.score
            except Exception as exc:  # local 3B judge can emit malformed structured output
                row[name] = None
                row[f"{name}_error"] = f"{type(exc).__name__}: {exc}"
        per_item.append(row)
        print(f"[{n}/{len(items)}] {r['id']}: " + ", ".join(f"{k}={row.get(k)}" for k in metrics))

    means = {}
    for name in metrics:
        vals = [row[name] for row in per_item if row.get(name) is not None]
        means[f"mean_{name}"] = (sum(vals) / len(vals)) if vals else None
        means[f"n_scored_{name}"] = len(vals)
        means[f"n_errored_{name}"] = sum(1 for row in per_item if row.get(name) is None)

    out = {"model": args.model, "n_items": len(items), **means, "per_item": per_item}
    Path(args.out).write_text(json.dumps(out, indent=2))
    print("means:", means)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
