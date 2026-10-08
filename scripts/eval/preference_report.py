"""Replay human preferences against the production ranker on an isolated SQLite DB."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from information_agent.db import Base
from information_agent.models import Feedback, Item, User, Watch
from information_agent.ranking import ranked_items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("data/eval/20261008-labeling"))
    parser.add_argument("--metadata", type=Path, default=Path("data/eval/20261006/annotation_queue.csv"))
    args = parser.parse_args()
    manifest = json.loads((args.directory / "manifest.json").read_text())
    exported = json.loads((args.directory / "preferences.json").read_text())
    items = manifest["items"]
    digest = hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    if manifest["corpus_id"] != digest or exported["corpus_id"] != digest:
        parser.error("Frozen manifest and labels do not match")
    if exported.get("label_kind") != "historical_content_preference":
        parser.error("Expected human content-preference labels")
    labels = {}
    for row in exported["labels"]:
        if row["item_id"] in labels or type(row["preference"]) not in {int, str}:
            parser.error("Duplicate or invalid preference label")
        if row["preference"] not in (0, 1, "skip"):
            parser.error("Invalid preference label")
        labels[row["item_id"]] = row["preference"]
    ids = {row["item_id"] for row in items}
    if len(ids) != len(items) or labels.keys() - ids:
        parser.error("Unknown or duplicate sample IDs")
    if any(row["split"] not in {"train", "eval"} for row in items):
        parser.error("Invalid frozen split")
    metadata = {row["canonical_url"]: row for row in csv.DictReader(args.metadata.open(encoding="utf-8-sig"))}
    if any(row["url"] not in metadata for row in items):
        parser.error("Missing original source metadata")
    as_of = datetime.fromisoformat(exported["exported_at"]).astimezone(UTC)
    eval_ids = {row["item_id"] for row in items if row["split"] == "eval"}
    train = [row for row in items if row["split"] == "train" and labels.get(row["item_id"]) in (0, 1)]
    # Freeze time, not model output or scoring. Both arms call the deployed ranking function.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db, patch("information_agent.ranking.datetime", wraps=datetime) as clock:
        clock.now.return_value = as_of
        user = User(id="offline-eval", email="offline@example.invalid", password_hash="unused")
        db.add(user)
        db.flush()
        db.add_all(Watch(user_id=user.id, watch_id=watch) for watch in sorted({r["watch_id"] for r in items}))
        for number, row in enumerate(items):
            source = metadata[row["url"]]
            published = datetime.fromisoformat(row["published_at"]) if row.get("published_at") else None
            db.add(
                Item(
                    id=row["item_id"],
                    watch_id=row["watch_id"],
                    canonical_url=row["url"],
                    title=row["title"],
                    summary=row.get("summary", ""),
                    source_name=source["source_id"],
                    source_type=source["source_type"],
                    ingestion_mode="offline_replay",
                    event_key=source["event_id"],
                    published_at=published,
                    created_at=as_of - timedelta(seconds=number),
                )
            )
        db.flush()
        before = [row for row in ranked_items(db, user.id, limit=500, recent_only=False) if row["id"] in eval_ids]
        for number, row in enumerate(train):
            db.add(
                Feedback(
                    id=f"feedback-{number:03}",
                    user_id=user.id,
                    item_id=row["item_id"],
                    action="interested" if labels[row["item_id"]] else "not_interested",
                    created_at=as_of + timedelta(seconds=number),
                )
            )
        db.flush()
        after = [row for row in ranked_items(db, user.id, limit=500, recent_only=False) if row["id"] in eval_ids]
    engine.dispose()

    def arm(rows):
        top = [
            {
                "item_id": r["id"],
                "title": r["title"],
                "watch_id": r["watch_id"],
                "score": round(r["score"], 2),
                "preference": labels.get(r["id"]),
            }
            for r in rows[:5]
        ]
        complete = len(top) == 5 and all(r["preference"] in (0, 1) for r in top)
        positive = sum(r["preference"] == 1 for r in top)
        unknown = sum(r["preference"] not in (0, 1) for r in top)
        return {
            "p_at_5": positive / 5 if complete else None,
            "known_positive_count": positive,
            "unknown_count": unknown,
            "p_at_5_bounds": [positive / 5, (positive + unknown) / 5] if len(top) == 5 else None,
            "top5": top,
        }

    baseline, personalized = arm(before), arm(after)
    delta = None
    if baseline["p_at_5"] is not None and personalized["p_at_5"] is not None:
        delta = round(personalized["p_at_5"] - baseline["p_at_5"], 4)
    train_events = {metadata[r["url"]]["event_id"] for r in items if r["split"] == "train"}
    eval_events = {metadata[r["url"]]["event_id"] for r in items if r["split"] == "eval"}
    report = {
        "corpus_id": digest,
        "as_of": as_of.isoformat(),
        "sample_count": len(items),
        "labels": dict(Counter(str(value) for value in labels.values())),
        "training_feedback_count": len(train),
        "held_out_candidate_count": len(eval_ids),
        "shared_event_keys_between_splits": len(train_events & eval_events),
        "metadata_sha256": hashlib.sha256(args.metadata.read_bytes()).hexdigest(),
        "labels_sha256": hashlib.sha256((args.directory / "preferences.json").read_bytes()).hexdigest(),
        "baseline": baseline,
        "personalized": personalized,
        "p_at_5_delta": delta,
        "top5_overlap": len({r["id"] for r in before[:5]} & {r["id"] for r in after[:5]}),
        "limits": manifest["limits"]
        + [
            "One reader; 30 curated historical articles; no statistical or online causal claim.",
            "11 preassigned training slots, 19 held-out slots; skips are not negatives.",
            "Baseline already contains the production Valve-source penalty; no raw-recency comparison.",
            "Watch-level feedback cannot distinguish patches from team news within the same watch.",
            "Preference labels do not assess factual correctness, freshness, or original-link availability.",
        ],
    }
    output = args.directory / "preference-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
