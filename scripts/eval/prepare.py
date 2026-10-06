"""Export the current real item pool for human relevance annotation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from information_agent.db import SessionLocal
from information_agent.models import Item
from information_agent.personalization import article_url

FIELDS = (
    "sample_id",
    "watch_id",
    "item_watch_id",
    "event_id",
    "source_id",
    "source_type",
    "published_at",
    "canonical_url",
    "title",
    "relevance",
    "entity_match",
    "duplicate_of",
    "evidence_supported",
    "annotator_id",
    "notes",
)

NEGATIVE_TARGET = {
    "stock:002491": "stock:002296",
    "stock:002296": "stock:002491",
    "gold:london": "esports:lol",
    "esports:lol": "esports:valorant",
    "esports:cs2": "esports:lol",
    "esports:valorant": "esports:cs2",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/eval"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    queue_path = args.output_dir / "annotation_queue.csv"
    items_path = args.output_dir / "items.jsonl"
    if queue_path.exists() or items_path.exists():
        parser.error(f"{queue_path} already exists; move it before regenerating to preserve labels")

    with SessionLocal() as db:
        items = list(db.scalars(select(Item).order_by(Item.watch_id, Item.canonical_url)))

    rows = []
    normalized = []
    skipped_records = 0
    for item in items:
        if not article_url(item):
            skipped_records += 1
            continue
        stable_id = hashlib.sha256(item.canonical_url.encode()).hexdigest()[:16]
        published = item.published_at.isoformat() if item.published_at else ""
        for target_watch_id in (item.watch_id, NEGATIVE_TARGET.get(item.watch_id, "esports:lol")):
            rows.append(
                {
                    "sample_id": f"{stable_id}:{target_watch_id}",
                    "watch_id": target_watch_id,
                    "item_watch_id": item.watch_id,
                    "event_id": item.event_key,
                    "source_id": item.source_name,
                    "source_type": item.source_type,
                    "published_at": published,
                    "canonical_url": item.canonical_url,
                    "title": item.title,
                    "relevance": "",
                    "entity_match": "",
                    "duplicate_of": "",
                    "evidence_supported": "",
                    "annotator_id": "",
                    "notes": "",
                }
            )
        normalized.append(
            {
                "item_id": stable_id,
                "watch_id": item.watch_id,
                "title": item.title,
                "summary": item.summary[:500],
                "url": item.canonical_url,
                "published_at": published or None,
            }
        )

    with queue_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with items_path.open("w", encoding="utf-8") as handle:
        for item in normalized:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(
        f"Exported {len(normalized)} article links and {len(rows)} blank judgments; "
        f"skipped {skipped_records} API records without public articles"
    )


if __name__ == "__main__":
    main()
