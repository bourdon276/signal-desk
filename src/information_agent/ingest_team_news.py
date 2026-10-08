"""Publisher RSS metadata for subscribed CS2 teams; no article-body crawler."""

import json
import re
from datetime import timedelta
from threading import Lock

import feedparser
import httpx

from information_agent.db import SessionLocal
from information_agent.entities import normalize_entity_name
from information_agent.ingest_common import download, safe_link, store_item
from information_agent.ingest_fed import brief_text, published_at
from information_agent.ingest_pandascore import watched_teams
from information_agent.models import AgentRun, now_utc
from information_agent.news_quality import news_exclusion

KIND = "cs2_team_news_sync"
FEED_URL = "https://esportsinsider.com/feed?category_name=counter-strike"
LOCK = Lock()


def mentions_team(text: str, name: str) -> bool:
    if normalize_entity_name(name) == "teamspirit":
        # Spirit Academy is a separate roster; do not silently mix its news.
        text = re.sub(r"\b(?:team\s+)?spirit\s+academy(?:\s+green)?\b", "", text, flags=re.I)
        aliases = ("Team Spirit", "Spirit", "donk", "sh1ro")
    else:
        aliases = (name,)
    return any(re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.I) for alias in aliases)


def sync() -> dict:
    with LOCK, SessionLocal() as db:
        teams = watched_teams(db)
        if not teams:
            return {"status": "no_team_subscriptions", "created": 0}
        run = AgentRun(kind=KIND, status="running", detail="")
        db.add(run)
        db.commit()
        try:
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
                parsed = feedparser.parse(download(client, FEED_URL))
            if not parsed.entries:
                raise ValueError("RSS has no usable entries")
            stats = {"entries": len(parsed.entries), "matched": 0, "created": 0, "skipped": 0, "quality_excluded": 0}
            for entry in parsed.entries[:100]:
                title = brief_text(entry.get("title", ""))
                text = title + " " + brief_text(entry.get("summary", ""))
                url = safe_link(entry.get("link", ""), {"esportsinsider.com", "www.esportsinsider.com"})
                stamp = published_at(entry)
                if not url or not title or stamp is None or not now_utc() - timedelta(days=30) <= stamp <= now_utc():
                    stats["skipped"] += 1
                    continue
                for marker, name in teams.items():
                    if not mentions_team(text, name):
                        continue
                    if news_exclusion(title, marker, "Esports Insider · 战队新闻"):
                        stats["quality_excluded"] += 1
                        continue
                    stats["matched"] += 1
                    stats["created"] += store_item(
                        db,
                        watch_id=marker,
                        canonical_url=url,
                        title=title,
                        summary=f"Esports Insider 的 Counter-Strike 新闻索引提及 {name}。"
                        "仅收录标题、发布时间及原文链接；正文与具体结论请阅读原文。",
                        source_name="Esports Insider · 战队新闻",
                        source_type="media",
                        ingestion_mode="rss",
                        published_at=stamp,
                    )
                    # A shared URL is stored once; multi-team article mapping is a future improvement.
                    break
            run.status = "success"
            run.detail = json.dumps(stats)
            run.item_count = stats["created"]
            run.finished_at = now_utc()
            db.commit()
            return {"run_id": run.id, **stats}
        except Exception as exc:
            db.rollback()
            run.status = "failure"
            run.detail = type(exc).__name__
            run.finished_at = now_utc()
            db.add(run)
            db.commit()
            raise RuntimeError("Team news sync failed; existing items retained") from None


if __name__ == "__main__":
    print(sync())
