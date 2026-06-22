# Judge calibration report

**Judge:** `deterministic-lexical` (config `b37ebf08157f`)

- Probes: 12
- Raw agreement with human labels: **0.750** (threshold 0.8)
- Cohen's κ: **0.400** (threshold 0.6) — ❌ below

| Operation | Agree | Agreement |
|---|---|---|
| contains | 4/4 | 1.00 |
| entails | 4/5 | 0.80 |
| equivalent | 1/3 | 0.33 |

Disagreements: g5-aloe-safe-antonym-contradiction, e2-es-yellow-leaves-synonym-paraphrase, e3-es-pothos-toxic-vs-safe

> The deterministic lexical judge is the **reproducible offline floor**, not a human-aligned gate-backer: it cannot detect antonym contradictions ("safe" vs "toxic") or morphological synonyms, which is exactly why production gates are backed by the calibrated LLM judge (`--judge llm`). This record is reported, not merge-blocking, for the deterministic judge.
