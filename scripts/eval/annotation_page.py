"""Build a private, offline preference annotation page from a frozen news corpus."""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from baseline import load_items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, default=Path("data/eval/20261006/items.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/eval/20261008-labeling"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    groups = defaultdict(list)
    for row in load_items(args.items):
        if row["watch_id"] in {"stock:002491", "stock:002296", "esports:cs2"}:
            groups[row["watch_id"]].append({k: v for k, v in row.items() if not k.startswith("_")})
    selected = []
    # Fix the corpus BEFORE seeing labels: all 10 stock samples + 20 CS2 samples.
    for watch, cap in [("stock:002491", 6), ("stock:002296", 4), ("esports:cs2", 20)]:
        rows = sorted(groups[watch], key=lambda r: (r.get("published_at") or "", r["item_id"]))[-cap:]
        for i, row in enumerate(rows):
            row["split"] = "train" if i % 3 == 0 else "eval"
            selected.append(row)
    if len(selected) != 30:
        parser.error("Expected 30 frozen samples; choose a new explicit corpus rather than silently changing it")
    digest = hashlib.sha256(json.dumps(selected, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    manifest = {
        "corpus_id": digest[:16],
        "selection": "6 Tongding + 4 Huihuang + 20 CS2; newest per source tag",
        "limits": [
            "Historical local corpus, not a current production feed.",
            "No dedicated Team Spirit news in this snapshot.",
            "Preference labels are not factual correctness or entity relevance labels.",
        ],
        "items": selected,
    }
    manifest_path = args.output_dir / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        parser.error("Existing frozen manifest differs; use another output directory")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    template = Path(__file__).with_name("annotation_page.html").read_text()
    payload = json.dumps(manifest, ensure_ascii=False).replace("<", "\\u003c")
    (args.output_dir / "index.html").write_text(template.replace("__MANIFEST__", payload))
    print(
        json.dumps(
            {
                "page": str(args.output_dir / "index.html"),
                "samples": len(selected),
                "training": sum(r["split"] == "train" for r in selected),
                "corpus_id": digest[:16],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
