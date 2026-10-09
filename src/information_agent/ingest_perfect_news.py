"""Read public Perfect World share articles. Known links only, not a full-site feed."""

import json
from datetime import UTC, datetime, timedelta
from threading import Lock
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from information_agent.db import SessionLocal
from information_agent.ingest_common import download, safe_link, store_item
from information_agent.ingest_fed import brief_text
from information_agent.ingest_pandascore import watched_teams
from information_agent.ingest_team_news import mentions_team
from information_agent.models import AgentRun, Item, SearchBudget, now_utc
from information_agent.news_quality import news_exclusion

KIND = "perfect_world_news_sync"
DETAIL_URL = "https://appactivity.wmpvp.com/steamcn/app/news/getAppNewsById"
# A user supplied and verified this public share link. Do not enumerate nearby article IDs.
KNOWN_NEWS_IDS = (304545,)
LOCK = Lock()


def share_news_id(url: str) -> int:
    if not safe_link(url, {"news.wmpvp.com"}):
        raise ValueError("share_url")
    parts = urlsplit(url)
    params = parse_qs(parts.query)
    ids = params.get("id", [])
    if (
        parts.path != "/news.html"
        or len(ids) != 1
        or not ids[0].isascii()
        or not ids[0].isdigit()
        or not 1 <= len(ids[0]) <= 12
        or int(ids[0]) <= 0
        or (params.get("gameTypeStr") != ["2"] and params.get("game") != ["csgo"])
    ):
        raise ValueError("share_url")
    return int(ids[0])


def read_article(client: httpx.Client, news_id: int) -> dict:
    payload = json.loads(download(client, DETAIL_URL, params={"gameType": 2, "newsId": news_id}))
    return article_metadata(payload, news_id)


def reserve_import(db, user_id: str) -> bool:
    """Separate attempt counter; does not consume Tavily credits."""
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    day = now_utc().astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    for scope, cap in ((f"share:user:{user_id}:{day}", 5), (f"share:day:{day}", 30)):
        db.execute(insert(SearchBudget).values(scope=scope, credits=0).on_conflict_do_nothing(index_elements=["scope"]))
        changed = db.execute(
            update(SearchBudget)
            .where(SearchBudget.scope == scope, SearchBudget.credits < cap)
            .values(credits=SearchBudget.credits + 1)
        )
        if changed.rowcount != 1:
            db.rollback()
            return False
    db.commit()
    return True


def article_metadata(payload: dict, news_id: int) -> dict:
    if not isinstance(payload, dict) or payload.get("code") not in (0, 1):
        raise ValueError("publisher_response")
    result = payload.get("result")
    news = result.get("news") if isinstance(result, dict) else None
    if not isinstance(news, dict) or news.get("gameType") != 2 or news.get("newsId") != news_id:
        raise ValueError("article_identity")
    stamp = news.get("publishTime")
    if type(stamp) is not int or stamp <= 0:
        raise ValueError("article_date")
    published = datetime.fromtimestamp(stamp / 1000, UTC)
    title = brief_text(news.get("title", "")) if isinstance(news.get("title"), str) else ""
    summary = brief_text(news.get("summary", "")) if isinstance(news.get("summary"), str) else ""
    if not title:
        raise ValueError("article_title")
    tags = news.get("tagDTOList")
    tags = [tag for tag in tags[:50] if isinstance(tag, dict)] if isinstance(tags, list) else []
    names = [brief_text(tag["name"]) for tag in tags if isinstance(tag.get("name"), str)]
    interview = any(name in {"人物访谈", "采访", "专访"} for name in names)
    return {
        "title": title,
        "summary": "完美世界电竞公开详情摘要：" + (summary or "暂无摘要，请打开原文阅读。"),
        "published_at": published,
        "canonical_url": f"https://news.wmpvp.com/news.html?id={news_id}&gameTypeStr=2",
        "source_name": "完美世界电竞 · 战队采访" if interview else "完美世界电竞 · 战队新闻",
        "source_type": "media",
        "ingestion_mode": "api",
        "match_text": " ".join([title, summary, *names]),
    }


def sync() -> dict:
    with LOCK, SessionLocal() as db:
        teams = watched_teams(db)
        if not teams:
            return {"status": "no_team_subscriptions", "created": 0}
        run = AgentRun(kind=KIND, status="running", detail="")
        db.add(run)
        db.commit()
        stats = {"entries": 0, "matched": 0, "created": 0, "dropped": {}}
        try:
            known = db.scalars(
                select(Item.canonical_url)
                .where(
                    Item.source_name.in_(("完美世界电竞 · 战队新闻", "完美世界电竞 · 战队采访")),
                    Item.published_at >= now_utc() - timedelta(days=30),
                )
                .order_by(Item.published_at.desc())
                .limit(20)
            )
            news_ids = list(KNOWN_NEWS_IDS)
            for url in known:
                try:
                    news_ids.append(share_news_id(url))
                except ValueError:
                    continue
            with httpx.Client(timeout=12, follow_redirects=False, trust_env=False) as client:
                for news_id in list(dict.fromkeys(news_ids))[:20]:
                    values = read_article(client, news_id)
                    stats["entries"] += 1
                    text = values.pop("match_text")
                    if not now_utc() - timedelta(days=30) <= values["published_at"] <= now_utc():
                        stats["dropped"]["outside_30_days"] = stats["dropped"].get("outside_30_days", 0) + 1
                        continue
                    markers = [marker for marker, name in teams.items() if mentions_team(text, name)]
                    if not markers:
                        stats["dropped"]["entity_mismatch"] = stats["dropped"].get("entity_mismatch", 0) + 1
                        continue
                    marker = sorted(markers)[0]
                    reason = news_exclusion(values["title"], marker, values["source_name"])
                    if reason:
                        stats["dropped"][reason] = stats["dropped"].get(reason, 0) + 1
                        continue
                    stats["matched"] += 1
                    stats["created"] += int(store_item(db, watch_id=marker, **values))
            run.status = "success"
            run.item_count = stats["created"]
            run.detail = json.dumps(stats)
            run.finished_at = now_utc()
            db.commit()
            return stats
        except Exception as exc:
            db.rollback()
            run.status = "failure"
            run.detail = type(exc).__name__
            run.finished_at = now_utc()
            db.add(run)
            db.commit()
            raise RuntimeError("Perfect World share sync failed; existing items retained") from None


if __name__ == "__main__":
    print(sync())
