"""User-scoped nanobot tools with optional, bounded public news discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry

from information_agent.db import SessionLocal
from information_agent.models import Item
from information_agent.personalization import article_url, matches, user_scope
from information_agent.query_policy import display_title
from information_agent.ranking import ranked_items
from information_agent.web_search import FOCUSES, discover, targets


class SearchItems(Tool):
    def __init__(self, user_id: str, since: datetime | None = None, until: datetime | None = None) -> None:
        self.user_id = user_id
        self.since = since
        self.until = until

    @property
    def name(self) -> str:
        return "search_items"

    @property
    def description(self) -> str:
        return "Search only the signed-in user's watched, stored news items."

    @property
    def read_only(self) -> bool:
        return True

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "watch_id": {"type": "string", "maxLength": 64},
                "watch_ids": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 64},
                    "minItems": 1,
                    "maxItems": 26,
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["limit"],
            "additionalProperties": False,
        }

    async def execute(self, limit: int, watch_id: str | None = None, watch_ids: list[str] | None = None) -> list[dict]:
        with SessionLocal() as db:
            items = ranked_items(db, self.user_id, limit=500)
            if self.since is not None or self.until is not None:

                def in_window(item):
                    if not item["published_at"]:
                        return False
                    published = datetime.fromisoformat(item["published_at"])
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=UTC)
                    return (self.since is None or published >= self.since) and (
                        self.until is None or published < self.until
                    )

                items = [item for item in items if in_window(item)]
            if watch_id is not None:
                items = [
                    item for item in items if watch_id in item["matched_watch_ids"] or watch_id == item["watch_id"]
                ]
            if watch_ids is not None:
                items = [item for item in items if set(item["matched_watch_ids"] + [item["watch_id"]]) & set(watch_ids)]
            return [
                {
                    "id": item["id"],
                    "watch_id": item["watch_id"],
                    "title": display_title(item["title"], item["source_name"])[:200],
                    "published_at": item["published_at"],
                    "source_name": item["source_name"],
                    "ingestion_mode": item["ingestion_mode"],
                }
                for item in items[:limit]
            ]


class GetEvidence(Tool):
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    @property
    def name(self) -> str:
        return "get_evidence"

    @property
    def description(self) -> str:
        return "Return source metadata and a short excerpt for one watched stored item."

    @property
    def read_only(self) -> bool:
        return True

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"item_id": {"type": "string", "maxLength": 36}},
            "required": ["item_id"],
            "additionalProperties": False,
        }

    async def execute(self, item_id: str) -> dict | None:
        with SessionLocal() as db:
            item = db.get(Item, item_id)
            enabled, topics = user_scope(db, self.user_id)
            if item is None or not matches(item, enabled, topics):
                return None
            return {
                "id": item.id,
                "title": display_title(item.title, item.source_name)[:200],
                "summary": item.summary[:500],
                "url": article_url(item),
                "source_name": item.source_name,
                "source_type": item.source_type,
                "ingestion_mode": item.ingestion_mode,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            }


class SearchNews(Tool):
    def __init__(self, user_id: str, since: datetime | None, until: datetime | None):
        self.user_id, self.since, self.until = user_id, since, until

    @property
    def name(self):
        return "search_news"

    @property
    def description(self):
        return (
            "Discover public news for ONE subscribed stock or CS2 team, store metadata, return scoped IDs. "
            "Only public entity names go to the search provider. No arbitrary queries or URLs."
        )

    @property
    def read_only(self):
        return False

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "watch_id": {"type": "string", "maxLength": 64},
                "focus": {"type": "string", "enum": sorted(FOCUSES)},
            },
            "required": ["watch_id", "focus"],
            "additionalProperties": False,
        }

    async def execute(self, watch_id: str, focus: str):
        with SessionLocal() as db:
            target = targets(db, self.user_id).get(watch_id)
        if target is None:
            return {"status": "outside_supported_scope", "results": [], "search_credits": 0}
        result = await discover(target, focus, self.user_id)
        allowed_ids = set(result["results"])
        # Respect both current subscription scope and the question's local date window.
        # Filter before truncating so unrelated library items cannot crowd out discovery results.
        with SessionLocal() as db:
            candidates = ranked_items(db, self.user_id, limit=500)
        candidates = [r for r in candidates if r["id"] in allowed_ids]
        rows = []
        for row in candidates:
            stamp = datetime.fromisoformat(row["published_at"]) if row["published_at"] else None
            if stamp and stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            if (self.since is not None and (stamp is None or stamp < self.since)) or (
                self.until is not None and (stamp is None or stamp >= self.until)
            ):
                continue
            rows.append(
                {key: row[key] for key in ("id", "watch_id", "title", "published_at", "source_name", "ingestion_mode")}
            )
        return {**result, "results": rows[:5]}


def scoped_registry(
    user_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
    allow_search: bool = False,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(SearchItems(user_id, since, until))
    registry.register(GetEvidence(user_id))
    if allow_search:
        registry.register(SearchNews(user_id, since, until))
    return registry


def news_age_label(value: str | None) -> str:
    if not value:
        return "发布时间未知"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%d")
