"""User-scoped nanobot tools. The public API exposes only these two capabilities."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry

from information_agent.db import SessionLocal
from information_agent.models import Item
from information_agent.personalization import matches, user_scope
from information_agent.ranking import ranked_items


class SearchItems(Tool):
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

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
                    "title": item["title"][:200],
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
                "title": item.title[:200],
                "summary": item.summary[:500],
                "url": item.canonical_url,
                "source_name": item.source_name,
                "source_type": item.source_type,
                "ingestion_mode": item.ingestion_mode,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            }


def scoped_registry(user_id: str) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(SearchItems(user_id))
    registry.register(GetEvidence(user_id))
    return registry


def news_age_label(value: str | None) -> str:
    if not value:
        return "发布时间未知"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%d")
