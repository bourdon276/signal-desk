"""Prepare readable excerpts from known, subscribed public articles with bounded retries."""

from datetime import timedelta
from time import monotonic
from urllib.parse import urlsplit

import httpx
from sqlalchemy import or_, select

from information_agent.article_reader import SELECTORS, article_excerpt, read_full_article
from information_agent.db import SessionLocal
from information_agent.freshness import MATCH_SOURCE, recent_filter
from information_agent.ingest_common import safe_link
from information_agent.models import Item, now_utc
from information_agent.web_search import targets

PER_CATEGORY_LIMIT = 3
ROUND_SECONDS = 45


def sync() -> dict:
    stats = {"status": "completed", "entries": 0, "updated": 0, "failed": 0, "categories": {}}
    started = monotonic()
    with SessionLocal() as db:
        groups: dict[str, set[str]] = {}
        for target in targets(db).values():
            kind = "stock" if target["kind"] == "index" else target["kind"]
            groups.setdefault(kind, set()).add(target["watch_id"])
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            for kind, markers in sorted(groups.items()):
                counts = {"entries": 0, "updated": 0, "failed": 0, "errors": {}}
                stats["categories"][kind] = counts
                # Separate quotas prevent a busy stock feed from starving team or gold news.
                rows = db.scalars(select(Item).where(
                    Item.watch_id.in_(markers), recent_filter(), Item.article_body.is_(None),
                    Item.source_name != MATCH_SOURCE,
                    or_(Item.article_retry_after.is_(None), Item.article_retry_after <= now_utc()),
                    or_(*(Item.canonical_url.startswith(f"https://{host}/") for host in SELECTORS)),
                ).order_by(Item.published_at.desc(), Item.id).limit(30))
                for item in list(rows):
                    if counts["entries"] >= PER_CATEGORY_LIMIT or monotonic() - started >= ROUND_SECONDS:
                        break
                    if safe_link(item.canonical_url, set(SELECTORS)) is None:
                        continue
                    # PDFs have a separate, potentially expensive parser; keep those on demand.
                    if urlsplit(item.canonical_url).hostname == "static.cninfo.com.cn":
                        continue
                    counts["entries"] += 1
                    try:
                        result = read_full_article(client, item.canonical_url)
                        item.article_body = "reader:v2\n" + result["body"]
                        item.body_fetched_at = now_utc()
                        excerpt = article_excerpt(result["blocks"], item.watch_id)
                        if excerpt:
                            item.summary = excerpt
                        if isinstance(result.get("title"), str) and result["title"]:
                            item.title = result["title"][:500]
                        item.article_retry_after = None
                        item.article_last_error = None
                        counts["updated"] += 1
                    except Exception as exc:
                        # Store only a bounded error category, never response bodies or credentials.
                        delay = 6
                        error = type(exc).__name__
                        if isinstance(exc, httpx.HTTPStatusError):
                            error = f"http_{exc.response.status_code}"
                            if exc.response.status_code in {401, 403, 404, 429}:
                                delay = 24
                        elif isinstance(exc, ValueError):
                            error, delay = "article_unreadable", 24
                        item.article_last_error = error[:50]
                        item.article_retry_after = now_utc() + timedelta(hours=delay)
                        counts["failed"] += 1
                        counts["errors"][error] = counts["errors"].get(error, 0) + 1
                    db.commit()
                for key in ("entries", "updated", "failed"):
                    stats[key] += counts[key]
    if stats["failed"]:
        stats["status"] = "partial"
    stats["duration_ms"] = round((monotonic() - started) * 1000)
    return stats
