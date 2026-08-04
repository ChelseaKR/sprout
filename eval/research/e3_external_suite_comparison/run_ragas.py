"""E3: run Ragas over sprout's real golden eval set (golden_set.json).

Two tiers, run separately because they measure different things and have very different
compute/dependency costs:

1. Non-LLM metrics (`NonLLMContextPrecisionWithReference`, `NonLLMContextRecall`,
   `NonLLMStringSimilarity`) — pure string-distance scoring, no model calls at all. These
   compare the passages sprout's retriever actually returned (`retrieved_contexts`)
   against the passages sprout actually cited (`cited_quotes`, i.e. what `record.py`
   treats as ground truth). Fast, fully deterministic, reproducible without any API key
   or local model — the closest Ragas gets to sprout's own offline DeterministicJudge
   philosophy.

2. LLM-judged metrics (`Faithfulness`, `ContextPrecision`, `ContextRecall`,
   `AnswerRelevancy`) — Ragas' flagship metrics, which are prompted LLM calls under the
   hood (claim decomposition + NLI-style verification). Sprout's own CI eval gate is
   explicitly offline/zero-API-cost (ADR-0006, ADR-0009); this repo has no
   OpenAI/Anthropic API key configured for eval. To run these at all rather than skip
   them, this script points Ragas at a local Ollama model (qwen2.5:3b, temperature=0,
   no network egress beyond localhost:11434) via `langchain_ollama.ChatOllama`. This is a
   real, faithful run of Ragas' actual metric implementations — just against a much
   smaller/weaker judge model than Ragas' documented examples (typically gpt-4o-class).
   Treat the LLM-judged numbers as directionally informative, not as "what Ragas would
   say with GPT-4o" — that distinction is called out in the writeup.

Usage (run inside .venv-ext, the isolated venv with ragas/deepeval/torch installed):
    .venv-ext/bin/python eval/research/e3_external_suite_comparison/run_ragas.py \
        --golden eval/research/e3_external_suite_comparison/golden_set.json \
        --out eval/research/e3_external_suite_comparison/ragas_results.json \
        [--llm-tier none|ollama] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
    NonLLMContextPrecisionWithReference,
    NonLLMContextRecall,
    NonLLMStringSimilarity,
)
from ragas.dataset_schema import SingleTurnSample
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper


def load_items(path: str, limit: int | None) -> list[dict]:
    data = json.loads(Path(path).read_text())
    items = [r for r in data["items"] if r["applicable_to_groundedness"]]
    if limit:
        items = items[:limit]
    return items


def run_non_llm(items: list[dict]) -> dict:
    from ragas.dataset_schema import SingleTurnSample as S

    prec_metric = NonLLMContextPrecisionWithReference()
    rec_metric = NonLLMContextRecall()
    sim_metric = NonLLMStringSimilarity()

    per_item = []
    for r in items:
        retrieved = [c["text"] for c in r["retrieved_contexts"]]
        reference_ctx = r["cited_quotes"] or retrieved[:1]
        sample = S(
            user_input=r["question"],
            response=r["answer_text"],
            retrieved_contexts=retrieved,
            reference_contexts=reference_ctx,
            reference=" ".join(r["expected_facts"]) or r["answer_text"],
        )
        prec = prec_metric.single_turn_score(sample)
        rec = rec_metric.single_turn_score(sample)
        sim = sim_metric.single_turn_score(sample)
        per_item.append(
            {
                "id": r["id"],
                "non_llm_context_precision": prec,
                "non_llm_context_recall": rec,
                "non_llm_answer_similarity": sim,
            }
        )
    n = len(per_item)
    return {
        "n_items": n,
        "mean_context_precision": sum(p["non_llm_context_precision"] for p in per_item) / n,
        "mean_context_recall": sum(p["non_llm_context_recall"] for p in per_item) / n,
        "mean_answer_similarity": sum(p["non_llm_answer_similarity"] for p in per_item) / n,
        "per_item": per_item,
    }


def run_llm_tier(items: list[dict], model: str) -> dict:
    from langchain_ollama import ChatOllama
    from langchain_huggingface import HuggingFaceEmbeddings

    llm = LangchainLLMWrapper(ChatOllama(model=model, temperature=0, num_ctx=4096))
    embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    )

    rows = []
    for r in items:
        retrieved = [c["text"] for c in r["retrieved_contexts"]]
        rows.append(
            {
                "user_input": r["question"],
                "response": r["answer_text"],
                "retrieved_contexts": retrieved,
                "reference": " ".join(r["expected_facts"]) or r["answer_text"],
            }
        )
    ds = Dataset.from_list(rows)

    metrics = [Faithfulness(), ContextPrecision(), ContextRecall(), AnswerRelevancy()]
    t0 = time.time()
    result = evaluate(
        dataset=ds,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        raise_exceptions=False,
        show_progress=True,
    )
    elapsed = time.time() - t0
    df = result.to_pandas()
    per_item = []
    for i, r in enumerate(items):
        row = df.iloc[i]
        per_item.append(
            {
                "id": r["id"],
                "faithfulness": _nanfloat(row.get("faithfulness")),
                "context_precision": _nanfloat(row.get("context_precision")),
                "context_recall": _nanfloat(row.get("context_recall")),
                "answer_relevancy": _nanfloat(row.get("answer_relevancy")),
            }
        )
    means = {}
    for k in ("faithfulness", "context_precision", "context_recall", "answer_relevancy"):
        vals = [p[k] for p in per_item if p[k] is not None]
        means[f"mean_{k}"] = (sum(vals) / len(vals)) if vals else None
        means[f"n_scored_{k}"] = len(vals)
    return {"model": model, "elapsed_s": round(elapsed, 1), "n_items": len(items), **means, "per_item": per_item}


def _nanfloat(v):
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="eval/research/e3_external_suite_comparison/golden_set.json")
    ap.add_argument("--out", default="eval/research/e3_external_suite_comparison/ragas_results.json")
    ap.add_argument("--llm-tier", choices=["none", "ollama"], default="ollama")
    ap.add_argument("--llm-model", default="qwen2.5:3b")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    items = load_items(args.golden, args.limit)
    print(f"loaded {len(items)} applicable items")

    out = {"non_llm": run_non_llm(items)}
    print(
        "non-LLM: precision=%.4f recall=%.4f sim=%.4f"
        % (
            out["non_llm"]["mean_context_precision"],
            out["non_llm"]["mean_context_recall"],
            out["non_llm"]["mean_answer_similarity"],
        )
    )

    if args.llm_tier == "ollama":
        out["llm_tier"] = run_llm_tier(items, args.llm_model)
        print("llm-tier means:", {k: v for k, v in out["llm_tier"].items() if k.startswith("mean_")})

    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
