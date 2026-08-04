"""E3: ALCE-style citation precision/recall over sprout's real golden eval set.

ALCE (Gao, Yao & Chen, 2023, "Enabling Large Language Models to Generate Text with
Citations") scores attribution with an NLI model at the *statement* level: each generated
sentence carries a set of citations; recall asks whether the concatenation of that
sentence's cited passages entails the sentence; precision asks, per citation, whether it
is individually necessary/sufficient (dropping an irrelevant citation should not reduce
entailment). The paper uses a T5-11B NLI model (TRUE); this script substitutes a much
smaller, off-the-shelf NLI model that runs locally on CPU
(`MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli`, ~370MB) — a documented, honest
substitution, not the original TRUE checkpoint.

Sprout's generator (`ExtractiveGenerator` + `citation_guard`) attaches exactly ONE
citation to each rendered sentence (see `models.AnswerSentence.citation: Citation`,
singular) — sprout never emits a sentence backed by multiple citations. That is a real
architectural fact this script surfaces, not an assumption: with a singleton citation set,
ALCE's precision/recall distinction is mathematically forced to collapse (removing the
only citation always destroys entailment, so "is this citation necessary" is trivially
true whenever the sentence is entailed at all). To still get a genuine, non-degenerate
precision/recall split, this script reports TWO views:

  * sentence-level (own-citation): each sentence checked against only the one passage
    sprout actually cited for it. Precision == recall here by construction (see above) —
    reported for completeness/transparency, not as a novel finding.
  * item-level (pooled-citations): each sentence checked against the UNION of every
    passage cited anywhere in that answer (mirrors what the in-house GroundednessSuite's
    DeterministicJudge does — it checks each claim against the item's full `sources`
    list, not just its own citation). This gives a real recall (is the sentence supported
    by *some* cited passage) vs. precision (of the passages cited for the answer, how
    many are the specific one(s) needed to support at least one sentence, i.e. not
    padding) comparison.

Usage (needs `transformers`/`torch`, run inside .venv-ext):
    .venv-ext/bin/python eval/research/e3_external_suite_comparison/run_alce_citation_pr.py \
        --golden eval/research/e3_external_suite_comparison/golden_set.json \
        --out eval/research/e3_external_suite_comparison/alce_results.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

NLI_MODEL = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
ENTAIL_LABEL = "entailment"


def build_nli():
    from transformers import pipeline

    return pipeline("text-classification", model=NLI_MODEL, top_k=None, truncation=True)


def entails(nli, premise: str, hypothesis: str) -> tuple[bool, float]:
    """True if `premise` (the cited passage) entails `hypothesis` (the answer sentence)."""
    out = nli({"text": premise, "text_pair": hypothesis})
    scores = {d["label"].lower(): d["score"] for d in out}
    p_entail = scores.get(ENTAIL_LABEL, 0.0)
    best = max(scores, key=scores.get)
    return best == ENTAIL_LABEL, p_entail


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default="eval/research/e3_external_suite_comparison/golden_set.json")
    ap.add_argument("--out", default="eval/research/e3_external_suite_comparison/alce_results.json")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    data = json.loads(Path(args.golden).read_text())
    items = [r for r in data["items"] if r["applicable_to_groundedness"]]
    if args.limit:
        items = items[: args.limit]

    nli = build_nli()

    own_citation_results = []  # (item_id, sentence_idx, entailed)
    pooled_results = []  # (item_id, sentence_idx, entailed)
    item_summaries = []

    for r in items:
        sentences = r["sentence_citations"]
        pooled_sources = r["cited_quotes"]
        item_own = []
        item_pooled = []
        for i, s in enumerate(sentences):
            own_ok, own_score = entails(nli, s["citation_quote"], s["text"])
            own_citation_results.append((r["id"], i, own_ok, own_score))
            item_own.append(own_ok)

            # pooled: entailed if ANY cited passage in the whole answer entails it
            # (recall), track which passage(s) actually did the entailing (precision
            # signal: a cited passage that never entails any sentence is "unused").
            best_pooled = False
            best_score = 0.0
            entailing_src_idx = None
            for j, src in enumerate(pooled_sources):
                ok, score = entails(nli, src, s["text"])
                if ok and score > best_score:
                    best_pooled, best_score, entailing_src_idx = True, score, j
            pooled_results.append((r["id"], i, best_pooled, best_score))
            item_pooled.append((best_pooled, entailing_src_idx))

        # item-level citation precision (pooled view): fraction of the answer's cited
        # passages that were actually load-bearing for >=1 sentence (not padding).
        used_src_idx = {idx for ok, idx in item_pooled if ok and idx is not None}
        precision_pooled = (len(used_src_idx) / len(pooled_sources)) if pooled_sources else None

        item_summaries.append(
            {
                "id": r["id"],
                "n_sentences": len(sentences),
                "n_cited_sources": len(pooled_sources),
                "own_citation_recall": (sum(item_own) / len(item_own)) if item_own else None,
                "pooled_recall": (
                    sum(ok for ok, _ in item_pooled) / len(item_pooled) if item_pooled else None
                ),
                "pooled_precision_unused_sources": precision_pooled,
            }
        )

    n_sent = len(own_citation_results)

    def _rate(rows, idx=2):
        vals = [row[idx] for row in rows]
        return sum(vals) / len(vals) if vals else None

    out = {
        "nli_model": NLI_MODEL,
        "n_items": len(items),
        "n_sentences": n_sent,
        "own_citation": {
            "description": (
                "Per sentence, does its single cited passage (sprout's citation_guard "
                "attaches exactly one) entail it? Precision==recall by construction for "
                "a singleton citation set."
            ),
            "recall": _rate(own_citation_results),
            "precision": _rate(own_citation_results),  # identical by construction; see docstring
        },
        "pooled_citations": {
            "description": (
                "Per sentence, is it entailed by ANY passage cited anywhere in the same "
                "answer (recall); of the passages cited in the answer, what fraction "
                "were load-bearing for at least one sentence vs. unused/padding "
                "(precision proxy)."
            ),
            "recall": _rate(pooled_results),
            "precision_mean_over_items": (
                sum(
                    s["pooled_precision_unused_sources"]
                    for s in item_summaries
                    if s["pooled_precision_unused_sources"] is not None
                )
                / sum(1 for s in item_summaries if s["pooled_precision_unused_sources"] is not None)
            ),
        },
        "per_item": item_summaries,
    }

    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"n_items={out['n_items']} n_sentences={out['n_sentences']}")
    print(
        "own-citation recall=precision=%.4f"
        % out["own_citation"]["recall"]
    )
    print(
        "pooled recall=%.4f  pooled precision (fraction cited sources load-bearing)=%.4f"
        % (out["pooled_citations"]["recall"], out["pooled_citations"]["precision_mean_over_items"])
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
