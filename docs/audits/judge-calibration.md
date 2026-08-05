# Judge calibration report

**Judge:** `deterministic-lexical` (config `ff1ad7874e00`)

- Probes: 66
- Raw agreement with human labels: **0.955** (threshold 0.8)
- Cohen's κ: **0.906** (threshold 0.6) — ✅ meets

| Operation | Agree | Agreement |
|---|---|---|
| contains | 22/22 | 1.00 |
| entails | 27/27 | 1.00 |
| equivalent | 14/17 | 0.82 |

Disagreements: e2-es-yellow-leaves-synonym-paraphrase, e16-es-brown-tips-synonym-paraphrase, e17-en-root-rot-synonym-paraphrase

> The deterministic lexical judge is the **reproducible offline floor**: lexical coverage plus a negation/antonym polarity guard, not a general-purpose semantic judge. It still misses morphological synonyms and paraphrase that share little surface vocabulary, which is why production gates should ultimately be backed by the calibrated LLM judge (`--judge llm`) as the probe set grows. Pass `--gate` to `sprout calibrate` to fail the build below threshold; run without it to report only.
