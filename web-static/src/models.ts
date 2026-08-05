/**
 * Core domain types — a TypeScript mirror of `src/sprout/models.py`.
 *
 * These are plain data shapes (no classes, no runtime validation) since the browser
 * pipeline only ever *reads* an already-validated `index.json`/`config.json` pair
 * exported by the Python side (`scripts/export_web_bundle.py`); there is no ingest path
 * in the browser to protect with `extra="forbid"`-style checks.
 */

export type Provenance = "corpus" | "household";

export interface Chunk {
  chunk_id: string;
  doc_id: string;
  title: string;
  source: string;
  text: string;
  language: string;
  topic: string;
  source_name: string;
  url: string;
  license: string;
  fetch_date: string;
}

export interface RetrievedChunk {
  chunk: Chunk;
  score: number;
}

export interface Citation {
  chunk_id: string;
  doc_id: string;
  title: string;
  source: string;
  quote: string;
  license: string;
  fetch_date: string;
  url: string;
}

export interface AnswerSentence {
  text: string;
  chunk_id: string;
  citation: Citation;
  provenance: Provenance;
}

export interface Answer {
  question: string;
  language: string;
  sentences: AnswerSentence[];
  retrieved: RetrievedChunk[];
  refused: boolean;
  refusal_reason: string | null;
  refusal_text: string | null;
  is_safety_query: boolean;
  safety_notice: string | null;
  confidence: number;
  low_confidence: boolean;
  abstained: boolean;
  disclosure: string;
  as_of: string | null;
}

/** The concatenated answer prose (citation-verified sentences only). Mirrors `Answer.text`. */
export function answerText(answer: Answer): string {
  return answer.sentences.map((s) => s.text).join(" ");
}

/** What the user sees. Mirrors `Answer.display_text`. */
export function answerDisplayText(answer: Answer): string {
  const parts = answer.refused
    ? [answer.refusal_text ?? ""]
    : answer.sentences.map((s) => s.text);
  if (answer.safety_notice) {
    parts.push(answer.safety_notice);
  }
  return parts
    .filter((p) => p)
    .join(" ")
    .trim();
}

/** Unique citations in first-appearance order. Mirrors `Answer.citations`. */
export function answerCitations(answer: Answer): Citation[] {
  const seen = new Set<string>();
  const out: Citation[] = [];
  for (const s of answer.sentences) {
    if (!seen.has(s.chunk_id)) {
      seen.add(s.chunk_id);
      out.push(s.citation);
    }
  }
  return out;
}
