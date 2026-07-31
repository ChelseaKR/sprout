/**
 * Dependency-free bilingual (English/Spanish) text helpers.
 *
 * A byte-for-byte TypeScript mirror of `src/sprout/text.py`. Retrieval (BM25 + dense),
 * the extractive generator, and the guards all reduce text to tokens the *same* way
 * through this module, exactly as the Python side does, so "what is a token" cannot
 * drift between the port and the reference implementation. Everything here is pure and
 * deterministic: no randomness, no network, no locale dependence (no `Intl`, no
 * locale-sensitive `String` methods).
 */

// Bilingual stop-word set — copied from `text.py`'s `_STOPWORDS`, folded to the
// unaccented forms `tokenize()` actually produces (Python's `content_tokens` also
// NFKD-folds every token *before* the stop-word lookup, so accented entries in
// `_STOPWORDS` such as "está"/"están"/"cómo"/"qué" never match there either — this set
// keeps only the forms that are reachable, which is behaviourally identical).
const STOPWORDS: ReadonlySet<string> = new Set([
  // English
  "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by", "do", "does",
  "did", "for", "from", "had", "has", "have", "how", "i", "if", "in", "into", "is", "it",
  "its", "me", "my", "of", "on", "or", "our", "so", "than", "that", "the", "their",
  "them", "then", "there", "these", "they", "this", "to", "was", "were", "what", "when",
  "where", "which", "who", "why", "will", "with", "you", "your", "about", "can", "could",
  "should", "would", "am", "we", "us", "he", "she", "his", "her", "any", "all", "more",
  "most", "some", "such", "only", "own", "too", "very", "just", "also", "get", "got",
  // Spanish
  "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "de", "del", "que",
  "en", "es", "son", "ser", "esta", "estan", "al", "se", "su", "sus", "como", "por",
  "para", "con", "mi", "mis", "tu", "tus", "le", "lo", "te", "nos", "muy", "mas", "pero",
  "si", "ya", "este", "estas", "estos", "cuando", "donde", "cual", "porque", "puede",
  "pueden", "hay", "ha", "han", "soy",
]);

// Negation markers — copied verbatim from `text.py`'s `_NEGATIONS` (unaccented forms
// only, for the same fold-before-lookup reason as `STOPWORDS` above).
const NEGATIONS: ReadonlySet<string> = new Set([
  "no", "not", "never", "cannot", "cant", "without", "none", "neither", "nor", "nunca",
  "ni", "sin", "tampoco", "jamas", "nada", "ningun", "ninguna", "non",
]);

// Mirrors Python's `r"[0-9]+(?:\.[0-9]+)?|[^\W\d_]+"` under `re.UNICODE` (the Python 3
// default), where `[^\W\d_]` matches any Unicode *letter*. JS's `\w` is ASCII-only even
// with the `u` flag, so the letter branch uses `\p{L}` (Unicode property escape) instead
// to also match Spanish accented letters ("ó", "ñ", ...) as single tokens rather than
// splitting on them.
const TOKEN_RE = /[0-9]+(?:\.[0-9]+)?|\p{L}+/gu;
const SENTENCE_SPLIT_RE = /(?<=[.!?])\s+/;
const NEG_NT_RE = /\b\w+n't\b/i;

/** Fold accents so 'también' and 'tambien' tokenise identically (mirrors `unicodedata.normalize("NFKD", ...)`). */
export function stripAccents(token: string): string {
  // U+0300–U+036F is the Unicode "Combining Diacritical Marks" block — exactly the
  // marks NFKD decomposition splits accented letters into (e.g. "á" -> "a" + U+0301).
  return token.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
}

/** NFKC-normalize and remove invisible Unicode format characters. Mirrors `_strip_zero_width`. */
function stripZeroWidth(text: string): string {
  return text.normalize("NFKC").replace(/\p{Cf}/gu, "");
}

/** Lower-cased, accent-folded word/number tokens, in document order. */
export function tokenize(text: string): string[] {
  const out: string[] = [];
  for (const match of stripZeroWidth(text).matchAll(TOKEN_RE)) {
    out.push(stripAccents(match[0].toLowerCase()));
  }
  return out;
}

/**
 * A tiny, conservative bilingual suffix stripper — mirrors `text.py`'s `_stem`.
 *
 * Not a linguistic stemmer — just enough to fold the most common plural/verb
 * inflections ("leaves"->"leav", "watering"->"water", "plantas"->"plant") so a query and
 * the passage that answers it land on the same token. Numbers pass through untouched so
 * figures stay exact for grounding.
 */
function stem(token: string): string {
  if (/^\d+$/.test(token) || /\d/.test(token)) {
    return token;
  }
  for (const suffix of ["ndoles", "andolo", "iendo", "ando", "ciones", "cion", "mente"]) {
    if (token.endsWith(suffix) && token.length - suffix.length >= 3) {
      return token.slice(0, token.length - suffix.length);
    }
  }
  for (const suffix of ["ing", "ies", "ied"]) {
    if (token.endsWith(suffix) && token.length - suffix.length >= 3) {
      const stripped = token.slice(0, token.length - suffix.length);
      return suffix === "ies" || suffix === "ied" ? stripped + "y" : stripped;
    }
  }
  for (const suffix of ["es", "s"]) {
    if (token.endsWith(suffix) && token.length - suffix.length >= 3) {
      return token.slice(0, token.length - suffix.length);
    }
  }
  if (token.endsWith("ed") && token.length - 2 >= 3) {
    return token.slice(0, token.length - 2);
  }
  return token;
}

/** Stemmed, stop-word-free content tokens — the unit of retrieval and grounding. */
export function contentTokens(text: string): string[] {
  const out: string[] = [];
  for (const tok of tokenize(text)) {
    if (STOPWORDS.has(tok) || NEGATIONS.has(tok)) {
      continue;
    }
    out.push(stem(tok));
  }
  return out;
}

/** Unique content tokens of `text`. */
export function tokenSet(text: string): Set<string> {
  return new Set(contentTokens(text));
}

// Splits a query into clauses on coordinating conjunctions and clause punctuation, in
// both languages — mirrors `text.py`'s `_FACET_SPLIT_RE` (EXP-01). `\p{L}\p{N}_` stands
// in for Python's Unicode-aware `\w` so accented boundaries split identically.
const FACET_SPLIT_RE =
  /\s*(?:[,;?]+|(?<=[\p{L}\p{N}_])\s+(?:and|but|or|as well as|y|pero|o)\s+(?=[\p{L}\p{N}_]))\s*/giu;

/**
 * Split a query into per-clause content-token sets ("facets") — mirrors
 * `text.py::extract_facets`. Single-part questions yield one facet; empty or
 * stop-word-only clauses are dropped.
 */
export function extractFacets(query: string): Set<string>[] {
  const clauses = query
    .trim()
    .split(FACET_SPLIT_RE)
    .filter((c) => c !== undefined && c.trim() !== "");
  const facets: Set<string>[] = [];
  for (const clause of clauses) {
    const toks = tokenSet(clause);
    if (toks.size > 0) {
      facets.push(toks);
    }
  }
  return facets;
}

/** True if `text` contains an explicit negation marker (either language). */
export function hasNegation(text: string): boolean {
  if (NEG_NT_RE.test(text)) {
    return true;
  }
  return tokenize(text).some((tok) => NEGATIONS.has(tok));
}

// Domain-specific safety antonyms. Each pair mirrors `_ANTONYM_PAIRS` in text.py.
const ANTONYM_PAIRS: ReadonlyArray<ReadonlySet<string>> = [
  ["safe", "toxic"],
  ["safe", "poisonous"],
  ["nontoxic", "toxic"],
  ["harmless", "toxic"],
  ["harmless", "poisonous"],
  ["harmless", "dangerous"],
  ["edible", "toxic"],
  ["edible", "poisonous"],
  ["seguro", "toxico"],
  ["segura", "toxica"],
  ["seguros", "toxicos"],
  ["seguras", "toxicas"],
  ["seguro", "venenoso"],
  ["segura", "venenosa"],
  ["inofensivo", "toxico"],
  ["inofensiva", "toxica"],
  ["comestible", "venenoso"],
  ["comestible", "venenosa"],
  ["comestible", "toxico"],
  ["comestible", "toxica"],
].map((pair) => new Set(pair));

/** True when the texts assert opposite sides of a known safety antonym pair. */
export function hasAntonymConflict(a: string, b: string): boolean {
  const tokensA = new Set(tokenize(a));
  const tokensB = new Set(tokenize(b));
  for (const pair of ANTONYM_PAIRS) {
    const sideA = [...pair].filter((token) => tokensA.has(token));
    const sideB = [...pair].filter((token) => tokensB.has(token));
    if (sideA.length > 0 && sideB.length > 0 && !sideA.some((token) => sideB.includes(token))) {
      return true;
    }
  }
  return false;
}

/**
 * Split into trimmed sentences on terminal punctuation, preserving decimals.
 *
 * "Let the top 1.5 inches dry. Then water." -> ["Let the top 1.5 inches dry.",
 * "Then water."]. Decimal points do not split because the regex requires whitespace
 * after the punctuation.
 */
export function splitSentences(text: string): string[] {
  return text
    .trim()
    .split(SENTENCE_SPLIT_RE)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
}

/**
 * Fraction of `needle`'s content tokens that appear in `haystack`.
 *
 * A recall-style, asymmetric measure: 1.0 means every content word of the claim is
 * present in the source. Returns 1.0 for an empty needle (vacuously covered) so a
 * punctuation-only sentence never fails grounding spuriously.
 */
export function coverage(needle: string, haystack: string): number {
  const needleTokens = tokenSet(needle);
  if (needleTokens.size === 0) {
    return 1.0;
  }
  const hay = tokenSet(haystack);
  let present = 0;
  for (const tok of needleTokens) {
    if (hay.has(tok)) {
      present += 1;
    }
  }
  return present / needleTokens.size;
}

function intersectSize(a: ReadonlySet<string>, b: ReadonlySet<string>): number {
  let n = 0;
  const [small, large] = a.size <= b.size ? [a, b] : [b, a];
  for (const x of small) {
    if (large.has(x)) {
      n += 1;
    }
  }
  return n;
}

/** Jaccard similarity of the two texts' content-token sets. */
export function jaccard(a: string, b: string): number {
  const sa = tokenSet(a);
  const sb = tokenSet(b);
  if (sa.size === 0 && sb.size === 0) {
    return 1.0;
  }
  const unionSize = sa.size + sb.size - intersectSize(sa, sb);
  if (unionSize === 0) {
    return 0.0;
  }
  return intersectSize(sa, sb) / unionSize;
}

/** Collapse whitespace and lower-case for verbatim-containment checks. */
export function normalizeText(text: string): string {
  return stripZeroWidth(text).replace(/\s+/g, " ").trim().toLowerCase();
}

/** Case-insensitive, whitespace-insensitive substring test. */
export function containsPhrase(haystack: string, phrase: string): boolean {
  return normalizeText(haystack).includes(normalizeText(phrase));
}

/** Jaccard similarity of two content-token sets already computed (used by dedup/retrieval). */
export function jaccardSets(a: ReadonlySet<string>, b: ReadonlySet<string>): number {
  if (a.size === 0 && b.size === 0) {
    return 1.0;
  }
  const unionSize = a.size + b.size - intersectSize(a, b);
  return unionSize === 0 ? 0.0 : intersectSize(a, b) / unionSize;
}

/** Size of the intersection of two token sets (exported for retrieval overlap scoring). */
export function intersectionSize(a: ReadonlySet<string>, b: ReadonlySet<string>): number {
  return intersectSize(a, b);
}
