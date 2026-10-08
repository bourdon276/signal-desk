from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from information_agent.freshness import recent_filter, view_filter
from information_agent.models import Feedback, Item, Reading
from information_agent.news_quality import news_exclusion
from information_agent.personalization import article_url, candidate_filter, matches, overview, user_scope
from information_agent.preferences import KIND_LABELS, REASONS, content_kind, preference_key
from information_agent.query_policy import display_title


def ranked_items(
    db: Session,
    user_id: str,
    limit: int = 50,
    *,
    view: str = "all",
    recent_only: bool = True,
    apply_quality: bool = True,
    watch_id: str | None = None,
    diagnostics: dict | None = None,
) -> list[dict]:
    watch_ids, topics = user_scope(db, user_id)
    if diagnostics is not None:
        diagnostics.update(
            candidates=0,
            hidden_not_interested=0,
            hidden_duplicate=0,
            quality_excluded=0,
            eligible_count=0,
            unread_count=0,
            returned_count=0,
            candidate_limit_reached=False,
            omitted_by_limit=0,
            hiding_feedback=[],
        )
    if not watch_ids or (watch_id is not None and watch_id not in watch_ids):
        return []
    candidate_watches = {watch_id} if watch_id else watch_ids
    candidate_topics = [topic for topic in topics if topic.id == watch_id] if watch_id else topics
    items = list(
        db.scalars(
            select(Item)
            .where(
                candidate_filter(candidate_watches, candidate_topics),
                view_filter(view),
                recent_filter(datetime.now(UTC)) if recent_only else True,
            )
            .order_by(Item.published_at.desc().nulls_last(), Item.created_at.desc())
            .limit(500)
        )
    )
    if diagnostics is not None:
        diagnostics["candidate_limit_reached"] = len(items) == 500
    items = [item for item in items if matches(item, candidate_watches, candidate_topics)]
    if diagnostics is not None:
        diagnostics["candidates"] = len(items)
    if apply_quality:
        qualified = [item for item in items if not news_exclusion(item.title, item.watch_id, item.source_name)]
        if diagnostics is not None:
            diagnostics["quality_excluded"] = len(items) - len(qualified)
        items = qualified
    read_ids = set(db.scalars(select(Reading.item_id).where(Reading.user_id == user_id)))
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
        old_items = db.scalars(select(Item).where(Item.id.in_(missing_ids)))
        item_by_id.update({item.id: item for item in old_items})
    hidden_events: set[str] = set()
    hidden_items: set[str] = set()
    watch_weight = dict.fromkeys(watch_ids, 0)
    facet_weight: dict[tuple[str, str, str], int] = {}
    liked: set[str] = set()
    for event in feedback:
        item = item_by_id.get(event.item_id)
        if item is None:
            continue
        matched = matches(item, watch_ids, topics)
        if not matched:
            continue
        if event.action in {"interested", "not_interested"} and event.reason in REASONS:
            if event.action == "not_interested":
                hidden_items.add(item.id)
            else:
                liked.add(item.id)
            facet = preference_key(item, event.reason)
            if facet:
                direction = 1 if event.action == "interested" else -1
                for target in matched:
                    key = (target, *facet)
                    facet_weight[key] = max(-3, min(3, facet_weight.get(key, 0) + direction))
            continue
        if event.action == "duplicate":
            hidden_events.add(item.event_key)
        elif event.action == "not_interested":
            for target in matched:
                watch_weight[target] = max(-3, watch_weight[target] - 1)
            hidden_items.add(item.id)
        elif event.action == "interested":
            for target in matched:
                watch_weight[target] = min(3, watch_weight[target] + 1)
            liked.add(item.id)

    now = datetime.now(UTC)
    rows = []
    for item in items:
        if item.id in hidden_items:
            if diagnostics is not None:
                diagnostics["hidden_not_interested"] += 1
            continue
        if item.event_key in hidden_events:
            if diagnostics is not None:
                diagnostics["hidden_duplicate"] += 1
            continue
        published = item.published_at or item.created_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        age_hours = max(0, (now - published).total_seconds() / 3600)
        recency = max(0, 100 - age_hours / 24)
        matched = matches(item, watch_ids, topics)
        weight = sum(watch_weight[target] for target in matched) / len(matched)
        kind = content_kind(item)
        facet = sum(
            facet_weight.get((target, "kind", kind), 0) + facet_weight.get((target, "source", item.source_name), 0)
            for target in matched
        ) / len(matched)
        facet = max(-3, min(3, facet))
        score = round(recency + (weight + facet) * 15 + (10 if item.id in liked else 0), 2)
        reason = "按发布时间排序"
        if item.source_name == "Valve · Steam":
            score -= 40
            reason = "游戏官方公告已下调优先级"
        if weight < 0:
            reason = "该主题收到过没兴趣反馈，排序已下调"
        elif weight > 0:
            reason = "你对该主题表达过兴趣"
        if facet < 0:
            reason = "根据你对这类内容或来源的反馈下调"
        elif facet > 0:
            reason = "根据你对这类内容或来源的兴趣上调"
        rows.append(
            {
                "id": item.id,
                "watch_id": item.watch_id,
                "title": display_title(item.title, item.source_name),
                "summary": item.summary,
                "overview": overview(item),
                "matched_watch_ids": matched,
                "is_read": item.id in read_ids,
                "url": article_url(item),
                "source_name": item.source_name,
                "source_type": item.source_type,
                "ingestion_mode": item.ingestion_mode,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "event_key": item.event_key,
                "score": score,
                "reason": reason,
                "content_kind": kind,
                "content_kind_label": KIND_LABELS[kind],
            }
        )
    # Stable sorting preserves the database's recency order when scores tie.
    rows.sort(key=lambda row: -row["score"])
    if diagnostics is not None:
        blocked_ids = {item.id for item in items if item.id in hidden_items}
        blocked_events = {item.event_key for item in items if item.event_key in hidden_events}
        diagnostics["hiding_feedback"] = [
            {"id": event.id, "action": event.action, "title": item_by_id[event.item_id].title[:200]}
            for event in reversed(feedback)
            if event.item_id in item_by_id
            and (
                (event.action == "not_interested" and event.item_id in blocked_ids)
                or (event.action == "duplicate" and item_by_id[event.item_id].event_key in blocked_events)
            )
        ][:20]
        diagnostics.update(
            eligible_count=len(rows),
            unread_count=sum(not row["is_read"] for row in rows),
            returned_count=min(limit, len(rows)),
            omitted_by_limit=max(0, len(rows) - limit),
        )
    return rows[:limit]
