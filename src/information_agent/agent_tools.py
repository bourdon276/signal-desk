"""User-scoped nanobot tools. The public API exposes only these two capabilities."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry

from information_agent.db import SessionLocal
from information_agent.models import Item, Watch
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
                "limit": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["limit"],
            "additionalProperties": False,
        }

    async def execute(self, limit: int, watch_id: str | None = None) -> list[dict]:
        with SessionLocal() as db:
            items = ranked_items(db, self.user_id, limit=500)
            if watch_id is not None:
                items = [item for item in items if item["watch_id"] == watch_id]
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
            item = db.scalar(
                select(Item)
                .join(Watch, Watch.watch_id == Item.watch_id)
                .where(Item.id == item_id, Watch.user_id == self.user_id)
            )
            if item is None:
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
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d")
