# Judge calibration report

**Judge:** `deterministic-lexical` (config `b37ebf08157f`)

- Probes: 66
- Raw agreement with human labels: **0.909** (threshold 0.8)
- Cohen's κ: **0.807** (threshold 0.6) — ✅ meets

| Operation | Agree | Agreement |
|---|---|---|
| contains | 22/22 | 1.00 |
| entails | 25/27 | 0.93 |
| equivalent | 13/17 | 0.76 |

Disagreements: g5-aloe-safe-antonym-contradiction, e2-es-yellow-leaves-synonym-paraphrase, e3-es-pothos-toxic-vs-safe, g26-monstera-safe-antonym-contradiction, e16-es-brown-tips-synonym-paraphrase, e17-en-root-rot-synonym-paraphrase

> The deterministic lexical judge is the **reproducible offline floor**, not a human-aligned gate-backer: by design it still cannot detect antonym contradictions ("safe" vs "toxic") or morphological synonyms (see the disagreements above) — those are the kinds of errors a CI gate on this record will *not* catch. CI gates this record (`sprout calibrate --gate`) as a regression smoke-floor on the reproducible offline judge, catching gross coverage/negation breakage; it is not a certification of human-level semantic judgment. Backing a real production judging decision still requires calibrating and gating the LLM judge separately (`--judge llm --gate`, run with live credentials outside CI).
