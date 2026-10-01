from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from information_agent.models import Feedback, Item, Watch


def ranked_items(db: Session, user_id: str, limit: int = 50) -> list[dict]:
    watch_ids = list(db.scalars(select(Watch.watch_id).where(Watch.user_id == user_id)))
    if not watch_ids:
        return []
    items = list(
        db.scalars(
            select(Item)
            .where(Item.watch_id.in_(watch_ids))
            .order_by(Item.published_at.desc().nulls_last(), Item.created_at.desc())
            .limit(500)
        )
    )
    feedback = list(
        db.scalars(
            select(Feedback)
            .where(Feedback.user_id == user_id, Feedback.undone_at.is_(None))
            .order_by(Feedback.created_at, Feedback.id)
        )
    )
    # Preference events remain meaningful after their original card leaves
    # the bounded candidate window. Load only the referenced metadata.
    referenced_ids = {event.item_id for event in feedback}
    item_by_id = {item.id: item for item in items}
    missing_ids = referenced_ids - item_by_id.keys()
    if missing_ids:
        old_items = db.scalars(select(Item).where(Item.id.in_(missing_ids), Item.watch_id.in_(watch_ids)))
        item_by_id.update({item.id: item for item in old_items})
    hidden_events: set[str] = set()
    hidden_items: set[str] = set()
    watch_weight = dict.fromkeys(watch_ids, 0)
    liked: set[str] = set()
    for event in feedback:
        item = item_by_id.get(event.item_id)
        if item is None:
            continue
        if event.action == "duplicate":
            hidden_events.add(item.event_key)
        elif event.action == "not_interested":
            watch_weight[item.watch_id] = max(-3, watch_weight[item.watch_id] - 1)
            hidden_items.add(item.id)
        elif event.action == "interested":
            watch_weight[item.watch_id] = min(3, watch_weight[item.watch_id] + 1)
            liked.add(item.id)

    now = datetime.now(UTC)
    rows = []
    for item in items:
        if item.event_key in hidden_events or item.id in hidden_items:
            continue
        published = item.published_at or item.created_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        age_hours = max(0, (now - published).total_seconds() / 3600)
        recency = max(0, 100 - age_hours / 24)
        score = round(recency + watch_weight[item.watch_id] * 15 + (10 if item.id in liked else 0), 2)
        reason = "近期消息"
        if watch_weight[item.watch_id] < 0:
            reason = "该主题收到过没兴趣反馈，排序已下调"
        elif watch_weight[item.watch_id] > 0:
            reason = "你对该主题表达过兴趣"
        rows.append(
            {
                "id": item.id,
                "watch_id": item.watch_id,
                "title": item.title,
                "summary": item.summary,
                "url": item.canonical_url,
                "source_name": item.source_name,
                "source_type": item.source_type,
                "ingestion_mode": item.ingestion_mode,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "event_key": item.event_key,
                "score": score,
                "reason": reason,
            }
        )
    # Stable sorting preserves the database's recency order when scores tie.
    rows.sort(key=lambda row: -row["score"])
    return rows[:limit]
