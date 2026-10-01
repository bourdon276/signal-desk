"""Synchronize the Federal Reserve monetary-policy RSS feed.

Only the fixed, publisher-provided feed is fetched. Article pages are not crawled.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

import feedparser
import httpx
from sqlalchemy import select

from information_agent.db import SessionLocal
from information_agent.models import AgentRun, Item, now_utc

FEED_URL = "https://www.federalreserve.gov/feeds/press_monetary.xml"
MAX_FEED_BYTES = 2_000_000


class TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def brief_text(value: str) -> str:
    parser = TextOnly()
    parser.feed(value)
    return re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()[:280]


def fed_url(value: str) -> str | None:
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.hostname != "www.federalreserve.gov":
        return None
    return urlunsplit(("https", "www.federalreserve.gov", parts.path, parts.query, ""))


def published_at(entry: dict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is None:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def sync() -> dict:
    run = AgentRun(kind="fed_rss_sync", status="running", detail="", item_count=0)
    with SessionLocal() as db:
        db.add(run)
        db.commit()
        try:
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
                response = client.get(FEED_URL, headers={"User-Agent": "PersonalInfoAgent/0.1 RSS reader"})
                response.raise_for_status()
                if len(response.content) > MAX_FEED_BYTES:
                    raise ValueError("RSS feed exceeds size limit")
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError("invalid RSS feed")
            created = 0
            for entry in parsed.entries[:100]:
                url = fed_url(entry.get("link", ""))
                title = brief_text(entry.get("title", ""))[:500]
                if not url or not title:
                    continue
                if db.scalar(select(Item.id).where(Item.canonical_url == url)) is not None:
                    continue
                db.add(
                    Item(
                        watch_id="gold:london",
                        canonical_url=url,
                        title=title,
                        summary=brief_text(entry.get("summary", "")),
                        source_name="Federal Reserve Board",
                        source_type="official",
                        ingestion_mode="rss",
                        event_key=hashlib.sha256(url.encode()).hexdigest()[:32],
                        published_at=published_at(entry),
                    )
                )
                created += 1
            run.status = "success"
            run.item_count = created
            run.detail = f"feed={FEED_URL}; entries={len(parsed.entries)}"
            run.finished_at = now_utc()
            db.commit()
            return {"run_id": run.id, "created": created, "entries": len(parsed.entries)}
        except (httpx.HTTPError, ValueError) as exc:
            db.rollback()
            run.status = "failure"
            run.detail = str(exc)[:500]
            run.finished_at = now_utc()
            db.add(run)
            db.commit()
            raise


if __name__ == "__main__":
    print(sync())
