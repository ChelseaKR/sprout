/**
 * Which chunk topics carry toxicity or ingestion prose — a mirror of
 * `SAFETY_TOPIC_SLUGS` in `src/sprout/chunk.py`.
 *
 * A chunk's topic is the slugified Markdown heading, so a Spanish document heading its
 * section `## Toxicidad` yields `topic === "toxicidad"`, not `"toxicity"`. 8 of the 16
 * Spanish corpus documents do exactly that, 7 of them ASPCA-listed as toxic to pets.
 * Comparing against the bare English literal missed all of them, which left the vet /
 * poison-control escort depending on whether the question happened to contain a lexicon
 * keyword (issue #107).
 *
 * `tests/test_web_static_parity.py` fails if this set and the Python one diverge.
 */
export const SAFETY_TOPIC_SLUGS: ReadonlySet<string> = new Set([
  "toxicity",
  "toxicidad",
  "safety",
  "seguridad",
]);

/** True when this chunk's topic marks it as toxicity/ingestion content. */
export function isSafetyTopic(topic: string | undefined | null): boolean {
  return topic != null && SAFETY_TOPIC_SLUGS.has(topic);
}
