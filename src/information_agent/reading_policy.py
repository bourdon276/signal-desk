"""Delivery is distinct from reading: historical imports never imply a user read them."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select

from information_agent.models import Item


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def historical_import(item) -> bool:
    # Stable across visits: compare publication against first insertion, not today's clock.
    # Manual imports remain visible as an explicit action. No readings are fabricated.
    if item.ingestion_mode not in {"rss", "api", "search"}:
        return False
    if item.published_at is None:
        return True
    return aware(item.created_at) - aware(item.published_at) > timedelta(hours=24)


def daily_briefing(rows: list[dict], now: datetime, limit: int = 6) -> list[dict]:
    """Last 24h, at most two per sector, round-robin across watched objects."""
    buckets: dict[str, list[dict]] = {}
    for row in sorted(rows, key=lambda row: (-row['score'], row['id'])):
        if row['is_read'] or row.get('is_history') or row['content_kind'] == 'match':
            continue
        if not row['published_at']:
            continue
        stamp = aware(datetime.fromisoformat(row['published_at']))
        if not aware(now) - timedelta(hours=24) <= stamp <= aware(now):
            continue
        buckets.setdefault(row['watch_id'], []).append(row)
    selected, sectors = [], {}
    # First one per object, then a second. Missing sectors never get invented filler.
    for _ in range(2):
        for key, candidates in buckets.items():
            sector = 'stocks' if key.startswith(('stock:', 'index:')) else key.split(':')[0]
            if not candidates or sectors.get(sector, 0) >= 2 or len(selected) >= limit:
                continue
            row = candidates.pop(0)
            selected.append({**row, 'briefing_reason': '近24小时 · 分关注选取；' + row['reason']})
            sectors[sector] = sectors.get(sector, 0) + 1
    return selected


def initial_source_backfill(db, items: list) -> set[str]:
    """Keep only three current candidates from a source's first ten-minute import.

    Derived from immutable first-insert timestamps; no fake Reading events and no
    migration needed for sources that were already connected. Partition by source
    and object, not by user, so public collection stays shared.
    """
    automatic = [item for item in items if item.ingestion_mode in {"rss", "api", "search"}]
    if not automatic:
        return set()
    pairs = {(item.watch_id, item.source_name) for item in automatic}
    scope = or_(*(and_(Item.watch_id == watch, Item.source_name == source) for watch, source in pairs))
    starts = db.execute(select(Item.watch_id, Item.source_name, func.min(Item.created_at)).where(
        scope, Item.ingestion_mode.in_(["rss", "api", "search"]),
    ).group_by(Item.watch_id, Item.source_name)).all()
    batch = or_(*(and_(Item.watch_id == watch, Item.source_name == source,
                      Item.created_at >= start, Item.created_at <= start + timedelta(minutes=10))
                  for watch, source, start in starts))
    positions = select(
        Item.id,
        func.row_number().over(
            partition_by=(Item.watch_id, Item.source_name),
            order_by=(Item.published_at.desc().nulls_last(), Item.id),
        ).label("position"),
    ).where(batch, Item.ingestion_mode.in_(["rss", "api", "search"])).subquery()
    return set(db.scalars(select(positions.c.id).where(
        positions.c.position > 3, positions.c.id.in_([item.id for item in automatic]),
    )))
