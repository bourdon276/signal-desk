"""Enrich already discovered public Kitco articles, without crawling a site or spending search credits."""

from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from information_agent.article_reader import article_excerpt, read_full_article
from information_agent.db import SessionLocal
from information_agent.freshness import recent_filter
from information_agent.models import Item, Watch, now_utc


def sync() -> dict:
    stats = {"status": "completed", "entries": 0, "updated": 0, "failed": 0}
    with SessionLocal() as db:
        if db.scalar(select(Watch.id).where(Watch.watch_id == "gold:london").limit(1)) is None:
            return stats
        # Only known URLs in the current library; no ID enumeration or extra search requests.
        rows = list(db.scalars(select(Item).where(
            Item.watch_id == "gold:london", recent_filter(), Item.article_body.is_(None),
            Item.canonical_url.like("https://www.kitco.com/news/%"),
        ).order_by(Item.published_at.desc()).limit(5)))
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            for item in rows:
                if urlsplit(item.canonical_url).hostname != "www.kitco.com":
                    continue
                stats["entries"] += 1
                try:
                    result = read_full_article(client, item.canonical_url)
                    item.article_body = "reader:v2\n" + result["body"]
                    item.body_fetched_at = now_utc()
                    item.summary = article_excerpt(result["blocks"], item.watch_id)
                    if isinstance(result.get("title"), str) and result["title"]:
                        item.title = result["title"][:500]
                    stats["updated"] += 1
                except Exception:
                    stats["failed"] += 1
        db.commit()
    if stats["failed"]:
        stats["status"] = "partial"
    return stats
