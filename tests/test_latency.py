"""Latency budget test — QM-02: offline answer latency stays under the declared budget.

Sprout's offline default has no real per-token decoding: extractive generation slices
sentences from already-retrieved chunks synchronously, so "first-token latency" and
"answer latency" are the same event in this mode (the SSE endpoint chunks the *already
computed* answer for streaming display; it does not defer computation). The 200 ms budget
(`docs/ROADMAP.md`) is generous for an in-memory, no-network pipeline — this test is a
regression guard against an accidental O(n^2)/network-call creeping into the offline path,
not a precise hardware micro-benchmark. It previously did not exist despite being declared
an AUTO gate (QM-02); this closes that gap.
"""

from __future__ import annotations

import time

from sprout.answer import Assistant

_QUESTIONS = [
    "why are my monstera leaves yellowing?",
    "is pothos toxic to my cat?",
    "how do I fix a flat bicycle tire?",
    "¿con qué frecuencia riego mi monstera en invierno?",
]
_BUDGET_S = 0.2  # 200 ms — the offline first-token budget declared in docs/ROADMAP.md
_N_ROUNDS = 20  # repeat the small question set for a stable p95 estimate


def test_answer_latency_p95_under_budget(assistant: Assistant) -> None:
    samples: list[float] = []
    for _ in range(_N_ROUNDS):
        for question in _QUESTIONS:
            start = time.perf_counter()
            assistant.answer(question)
            samples.append(time.perf_counter() - start)

    samples.sort()
    p95 = samples[int(len(samples) * 0.95) - 1]
    assert p95 < _BUDGET_S, (
        f"p95 offline answer latency {p95 * 1000:.1f} ms exceeds the "
        f"{_BUDGET_S * 1000:.0f} ms budget over {len(samples)} samples"
    )
