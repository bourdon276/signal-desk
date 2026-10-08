"""Shared feed window; historical records remain stored for feedback and audit."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_

from information_agent.models import Item

RECENT_DAYS = 30
UPCOMING_DAYS = 7
MATCH_SOURCE = "PandaScore · CS2 赛事数据"


def recent_filter(now: datetime | None = None):
    now = now or datetime.now(UTC)
    timestamp = Item.published_at
    upcoming = and_(
        Item.source_name == MATCH_SOURCE,
        or_(Item.title.startswith("待赛："), Item.title.endswith(" · 赛程")),
    )
    # Upcoming fixtures have a bounded future window; news never does.
    return and_(
        timestamp >= now - timedelta(days=RECENT_DAYS),
        or_(
            and_(timestamp <= now, ~upcoming),
            and_(upcoming, timestamp >= now, timestamp <= now + timedelta(days=UPCOMING_DAYS)),
        ),
    )


def view_filter(view: str):
    if view == "news":
        return Item.source_name != MATCH_SOURCE
    if view == "matches":
        return Item.source_name == MATCH_SOURCE
    return True
