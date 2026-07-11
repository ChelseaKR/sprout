"""One-shot: turn the content-workflow JSON output into committed corpus + eval files.

Also re-mirrors ``corpus/`` and ``config/sprout.yaml`` into ``src/sprout/data/`` (the
packaged fallback ``pipx install sprout`` ships with) so the two copies can never
silently drift apart — see FIX-06 in docs/ideation/02-large-scale-fixes.md.
``tests/test_resources.py`` asserts the two trees stay byte-identical; this script is
the other half of that guarantee: regenerating content now updates both copies.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC_DATA = ROOT / "src" / "sprout" / "data"
SRC = Path(sys.argv[1])
data = json.loads(SRC.read_text(encoding="utf-8"))
data = data.get("result", data)

processed = ROOT / "corpus" / "processed"
processed.mkdir(parents=True, exist_ok=True)
suites_dir = ROOT / "eval" / "suites"
suites_dir.mkdir(parents=True, exist_ok=True)

manifest_docs: list[dict[str, object]] = []
for doc in data["documents"]:
    slug = doc["slug"]
    (processed / f"{slug}.md").write_text(doc["en_markdown"].rstrip() + "\n", encoding="utf-8")
    (processed / f"{slug}.es.md").write_text(doc["es_markdown"].rstrip() + "\n", encoding="utf-8")
    common = {
        "source_name": "Synthetic Plant-Care Notes",
        "url": f"https://example.invalid/{slug}",
        "license": "CC0-1.0",
        "fetch_date": "2026-05-01",
        "topic": "care",
    }
    manifest_docs.append({"file": f"{slug}.md", "title": doc["title_en"], "language": "en", **common})
    manifest_docs.append({"file": f"{slug}.es.md", "title": doc["title_es"], "language": "es", **common})

manifest = {
    "_note": "Synthetic, CC0-1.0 reference corpus. Toxicity reflects publicly known status; "
    "prose is original. Not authoritative horticulture. See docs/cards/data-card-corpus.md.",
    "documents": sorted(manifest_docs, key=lambda d: str(d["file"])),
}
(ROOT / "corpus" / "manifest.yaml").write_text(
    yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
)

total_cases = 0
for suite in data["suites"]:
    cases = suite["cases"]
    # Drop any keys that are None so the YAML stays clean.
    clean = [{k: v for k, v in c.items() if v is not None} for c in cases]
    (suites_dir / f"{suite['key']}.yaml").write_text(
        yaml.safe_dump({"cases": clean}, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    total_cases += len(clean)
    print(f"  {suite['key']}: {len(clean)} cases")

probes = data.get("probes", [])
(ROOT / "eval" / "judge_probes.yaml").write_text(
    yaml.safe_dump({"probes": probes}, sort_keys=False, allow_unicode=True), encoding="utf-8"
)

print(f"documents: {len(data['documents'])} plants (x2 languages)")
print(f"eval cases: {total_cases}")
print(f"judge probes: {len(probes)}")

# --- FIX-06: keep the packaged src/sprout/data/ mirror in sync -------------------------
# Replace wholesale (not just overwrite) so a doc removed from corpus/ also disappears
# from the packaged copy, instead of lingering as a stale, orphaned file.
packaged_corpus = SRC_DATA / "corpus"
if packaged_corpus.exists():
    shutil.rmtree(packaged_corpus)
shutil.copytree(ROOT / "corpus", packaged_corpus)
shutil.copyfile(ROOT / "config" / "sprout.yaml", SRC_DATA / "sprout.yaml")
print(f"mirrored corpus/ + config/sprout.yaml -> {SRC_DATA.relative_to(ROOT)}/")
