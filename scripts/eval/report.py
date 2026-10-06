"""Compare the frozen keyword baseline with source-tagged recency on human labels."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from baseline import load_items, rank


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, default=Path("data/eval/items.jsonl"))
    parser.add_argument("--labels", type=Path, default=Path("data/eval/annotation_queue.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/eval/report.json"))
    args = parser.parse_args()

    items = load_items(args.items)
    by_id = {item["item_id"]: item for item in items}
    labels: dict[tuple[str, str], int] = {}
    duplicate_of: dict[tuple[str, str], str] = {}
    with args.labels.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            value = row["relevance"].strip()
            if value not in {"", "0", "1"}:
                parser.error(f"invalid relevance for {row['sample_id']}: {value!r}")
            if value:
                key = (row["watch_id"], row["sample_id"].split(":", 1)[0])
                if key in labels:
                    parser.error(f"duplicate judgment for {key}")
                labels[key] = int(value)
                duplicate_of[key] = row["duplicate_of"].strip()

    baseline_rows: dict[str, list[str]] = defaultdict(list)
    for row in rank(items):
        baseline_rows[row["watch_id"]].append(row["item_id"])
    watches = sorted({watch_id for watch_id, _ in labels})
    results = []
    for watch_id in watches:
        judged = {item_id: value for (target, item_id), value in labels.items() if target == watch_id}
        tagged = [item for item in items if item["watch_id"] == watch_id]
        tagged.sort(key=lambda item: (item["_timestamp"] is None, -(item["_timestamp"] or 0), item["item_id"]))
        candidates = {
            "keyword_recency": baseline_rows[watch_id],
            "source_tagged_recency": [item["item_id"] for item in tagged],
        }
        methods = {}
        for name, ordered in candidates.items():
            top = ordered[:5]
            complete = len(top) == 5 and all(item_id in judged for item_id in top)
            judged_top = [item_id for item_id in top if item_id in judged]
            methods[name] = {
                "judged_at_5": len(judged_top),
                "returned_at_5": len(top),
                "p_at_5": round(sum(judged[item_id] for item_id in top) / 5, 3) if complete else None,
                "relevant_at_5": sum(judged[item_id] for item_id in judged_top),
                "duplicate_rate_at_5": round(
                    sum(bool(duplicate_of[(watch_id, item_id)]) for item_id in judged_top) / len(top), 3
                )
                if complete
                else None,
                "false_positive_urls": [by_id[item_id]["url"] for item_id in judged_top if not judged[item_id]],
                "top_ids": top,
            }
        results.append(
            {
                "watch_id": watch_id,
                "judged": len(judged),
                "positive": sum(judged.values()),
                "negative": len(judged) - sum(judged.values()),
                "methods": methods,
            }
        )

    report = {
        "unique_links": len(by_id),
        "labeled_unique_links": len({item_id for _, item_id in labels}),
        "human_judgments": len(labels),
        "watch_results": results,
        "limits": [
            "P@5 is N/A unless all original top five items are judged; "
            "unlabeled items are never filtered out before ranking.",
            "The corpus is intentionally curated and small; it does not estimate production relevance.",
            "Source tags were assigned during manual intake, so this comparison measures entity coverage, "
            "not learning from feedback.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "unique_links": len(by_id),
                "labeled_unique_links": report["labeled_unique_links"],
                "human_judgments": len(labels),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
