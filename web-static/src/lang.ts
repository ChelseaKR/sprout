/**
 * Dependency-free language detection over the supported set (English, Spanish) — a
 * mirror of `lang.py`. The optional `langdetect` tie-breaker Python falls back to only
 * when that (non-default) package is installed has no TypeScript equivalent; the
 * deterministic offline pipeline this port targets does not depend on it either (a bare
 * `pip install sprout` / `uv sync` does not pull `langdetect` in), so both
 * implementations agree without it.
 */

import { tokenize } from "./text.js";

export const SUPPORTED: readonly string[] = ["en", "es"];
export const DEFAULT_LANGUAGE = "en";

// Function words that are strong, mutually-exclusive signals for each language.
const MARKERS: Record<string, ReadonlySet<string>> = {
  es: new Set([
    "el", "la", "los", "las", "una", "unos", "unas", "que", "de", "del", "como", "cómo",
    "por", "para", "con", "es", "son", "está", "están", "mi", "su", "pero", "porque",
    "cuando", "donde", "muy", "más", "hoja", "hojas", "planta", "agua", "luz", "tóxica",
    "tóxico", "gato", "perro", "regar", "riego", "amarilla", "amarillas",
  ]),
  en: new Set([
    "the", "and", "is", "are", "of", "to", "in", "my", "why", "how", "what", "for",
    "with", "leaf", "leaves", "plant", "water", "light", "toxic", "cat", "dog", "yellow",
    "yellowing", "watering", "should", "does",
  ]),
};

// Characters that only appear in Spanish text in this domain.
const SPANISH_CHARS = new Set(["ñ", "¿", "¡", "á", "é", "í", "ó", "ú", "ü"]);

/**
 * Return the best-guess BCP-47 tag in `SUPPORTED`, or `default_` — mirrors
 * `detect_language`.
 */
export function detectLanguage(text: string, defaultLang: string = DEFAULT_LANGUAGE): string {
  const lowered = text.toLowerCase();
  if ([...lowered].some((ch) => SPANISH_CHARS.has(ch))) {
    return "es";
  }

  const toks = new Set(tokenize(text));
  if (toks.size === 0) {
    return defaultLang;
  }

  const scores: Record<string, number> = {};
  for (const lang of SUPPORTED) {
    const markers = MARKERS[lang] as ReadonlySet<string>;
    let count = 0;
    for (const t of toks) {
      if (markers.has(t)) {
        count += 1;
      }
    }
    scores[lang] = count;
  }
  const best = SUPPORTED.reduce((a, b) => ((scores[b] as number) > (scores[a] as number) ? b : a));
  if (scores[best] === 0 || scores["en"] === scores["es"]) {
    return defaultLang;
  }
  return best;
}
