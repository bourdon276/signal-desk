"""Import manually reviewed source links without fetching third-party pages."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from information_agent.db import SessionLocal
from information_agent.domain import valid_watch
from information_agent.models import Item

FILE = Path(__file__).resolve().parents[1] / "docs" / "demo_links.json"


def main() -> None:
    records = json.loads(FILE.read_text(encoding="utf-8"))
    created = 0
    with SessionLocal() as db:
        for row in records:
            if not valid_watch(row["watch_id"]):
                raise ValueError(f"invalid watch_id: {row['watch_id']}")
            if db.scalar(select(Item.id).where(Item.canonical_url == row["url"])):
                continue
            db.add(
                Item(
                    watch_id=row["watch_id"],
                    canonical_url=row["url"],
                    title=row["title"],
                    summary="",
                    source_name=row["source_name"],
                    source_type=row["source_type"],
                    ingestion_mode="manual_link",
                    event_key=hashlib.sha256(row["url"].encode()).hexdigest()[:32],
                    published_at=datetime.fromisoformat(row["published_at"].replace("Z", "+00:00")),
                )
            )
            created += 1
        db.commit()
    print({"created": created, "total_reviewed": len(records)})


if __name__ == "__main__":
    main()
