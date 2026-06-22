"""One-shot: turn the content-workflow JSON output into committed corpus + eval files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
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
