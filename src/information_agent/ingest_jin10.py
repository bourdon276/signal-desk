"""Gold and US macro news from authenticated Jin10 tools, with cadence and call caps."""

import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from information_agent.config import settings
from information_agent.db import SessionLocal
from information_agent.gold_news import gold_reason
from information_agent.ingest_common import safe_link, store_item
from information_agent.jin10_client import call_data, configured, error_code, session, tool_catalog
from information_agent.models import AgentRun, Item, SearchBudget, SearchCache, Watch, now_utc

KIND = "jin10_gold_sync"
CACHE_KEY = hashlib.sha256(b"jin10:gold:macro:v1").hexdigest()
PLANS = (("search_flash", "黄金"), ("search_flash", "美国"),
         ("search_flash", "美联储"), ("search_news", "黄金"))


def plain_text(value) -> str:
    if not isinstance(value, str) or len(value) > 200_000:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    for node in soup.select("script, style, iframe, form"):
        node.decompose()
    return re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True)).strip()


def published_at(value) -> datetime | None:
    if not isinstance(value, str) or len(value) > 60:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return stamp.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def normalize(row: dict, flash: bool, now: datetime) -> tuple[dict | None, str | None]:
    if not isinstance(row, dict):
        return None, "invalid_row"
    stamp = published_at(row.get("time"))
    if stamp is None or not now - timedelta(days=30) <= stamp <= now:
        return None, "missing_or_outside_date"
    raw_id = row.get("id")
    article_id = str(raw_id) if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else ""
    if not re.fullmatch(r"[0-9]{1,24}", article_id):
        return None, "invalid_identity"
    expected = f"https://{'flash' if flash else 'xnews'}.jin10.com/{'detail' if flash else 'details'}/{article_id}"
    raw_url = row.get("url", expected)
    if not isinstance(raw_url, str):
        return None, "unapproved_url"
    url = safe_link(raw_url, {"flash.jin10.com" if flash else "xnews.jin10.com"})
    if url is None or urlsplit(url).path != urlsplit(expected).path:
        return None, "unapproved_url"
    content = plain_text(row.get("content")) if flash else plain_text(row.get("introduction"))
    title = plain_text(row.get("title"))
    if not title and flash:
        title = content[:90] + ("…" if len(content) > 90 else "")
    if not title or not gold_reason(title + " " + content):
        return None, "entity_mismatch"
    if re.search(r"首饰|珠宝|金店|回收报价", title):
        return None, "not_gold_market_news"
    values = {
        "watch_id": "gold:london", "title": title[:500], "summary": content[:500],
        "canonical_url": expected, "published_at": stamp,
        "source_name": "金十数据 · 黄金与宏观快讯" if flash else "金十数据 · 黄金与宏观资讯",
        "source_type": "media", "ingestion_mode": "api",
    }
    # Only a flash tool's content is complete here; a news introduction is not a body.
    if flash and content:
        values.update(article_body="reader:v2\n" + content, body_fetched_at=now)
    return values, None


def _insert(db):
    return pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert


def reserve_tool(db) -> bool:
    day = now_utc().astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    scope = "jin10:day:" + day
    db.execute(_insert(db)(SearchBudget).values(
        scope=scope, credits=0,
    ).on_conflict_do_nothing(index_elements=["scope"]))
    changed = db.execute(update(SearchBudget).where(
        SearchBudget.scope == scope, SearchBudget.credits < settings.jin10_daily_tool_limit,
    ).values(credits=SearchBudget.credits + 1))
    if changed.rowcount != 1:
        db.rollback()
        return False
    db.commit()
    return True


def claim(db) -> str | None:
    now, token = now_utc(), str(uuid.uuid4())
    db.execute(_insert(db)(SearchCache).values(
        key=CACHE_KEY, payload="{}", expires_at=now, lease_until=now, lease_token="",
    ).on_conflict_do_nothing(index_elements=["key"]))
    changed = db.execute(update(SearchCache).where(
        SearchCache.key == CACHE_KEY, SearchCache.expires_at <= now, SearchCache.lease_until <= now,
    ).values(lease_until=now + timedelta(minutes=5), lease_token=token))
    if changed.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    return token


def news_body(data: dict, article_id: str) -> str:
    if str(data.get("id", "")) != article_id:
        raise ValueError("jin10_article_identity")
    body = plain_text(data.get("content"))
    if len(body) < 40:
        raise ValueError("jin10_article_body_missing")
    return body


async def _read_news(article_id: str) -> str:
    async with session() as active:
        catalog = await tool_catalog(active)
        with SessionLocal() as db:
            if not reserve_tool(db):
                raise ValueError("jin10_budget_exhausted")
        return news_body(await call_data(active, catalog, "get_news", {"id": article_id}), article_id)


def read_news(url: str) -> dict:
    approved = safe_link(url, {"xnews.jin10.com"})
    matched = re.fullmatch(r"/details/([0-9]{1,24})", urlsplit(approved).path) if approved else None
    if matched is None:
        raise ValueError("unsupported_source")
    body = asyncio.run(asyncio.wait_for(_read_news(matched[1]), timeout=40))
    return {"body": body, "blocks": body.split("\n")}


async def inspect_flash() -> dict:
    """Private provider format diagnosis; one capped call, no raw article bodies or secrets."""
    async with session() as active:
        catalog = await tool_catalog(active)
        with SessionLocal() as db:
            if not reserve_tool(db):
                return {"status": "budget_exhausted"}
        data = await call_data(active, catalog, "search_flash", {"keyword": "黄金"})
        rows = data.get("items", [])
        shapes = []
        for row in rows[:3] if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            value = row.get("id")
            sample = {"keys": [key for key in row if re.fullmatch(r"[A-Za-z_]{1,50}", key)],
                      "id_type": type(value).__name__, "id_length": len(str(value)),
                      "id_numeric": bool(re.fullmatch(r"[0-9]+", str(value))),
                      "time_type": type(row.get("time")).__name__}
            url = row.get("url")
            approved = safe_link(url, {"flash.jin10.com"}) if isinstance(url, str) else None
            if approved:
                part = urlsplit(approved).path.rsplit("/", 1)[-1]
                sample.update(url_id_length=len(part), url_id_numeric=bool(re.fullmatch(r"[0-9]+", part)),
                              id_matches_url=str(value) == part)
            shapes.append(sample)
        return {"status": "success", "entries": len(rows) if isinstance(rows, list) else 0, "shapes": shapes}


async def collect(db, stats: dict):
    async with session() as active:
        catalog = await tool_catalog(active)
        for tool, keyword in PLANS:
            if tool not in catalog:
                stats["errors"]["tool_unavailable"] = stats["errors"].get("tool_unavailable", 0) + 1
                continue
            if not reserve_tool(db):
                stats["budget_exhausted"] = True
                break
            stats["tool_calls"] += 1
            try:
                data = await call_data(active, catalog, tool, {"keyword": keyword})
                rows = data.get("items")
                if not isinstance(rows, list):
                    raise ValueError("jin10_items_format")
                stats["truncated"] |= len(rows) > 100 or bool(data.get("has_more"))
                created = 0
                for row in rows[:100]:
                    stats["entries"] += 1
                    values, reason = normalize(row, tool == "search_flash", now_utc())
                    if reason:
                        stats["dropped"][reason] = stats["dropped"].get(reason, 0) + 1
                        continue
                    stats["matched"] += 1
                    created += int(store_item(db, **values))
                db.commit()
                stats["created"] += created
            except Exception as exc:
                db.rollback()
                code = error_code(exc)
                stats["errors"][code] = stats["errors"].get(code, 0) + 1
        # Prepare at most two news bodies; flash content is already complete.
        items = list(db.scalars(select(Item).where(
            Item.watch_id == "gold:london", Item.source_name == "金十数据 · 黄金与宏观资讯",
            Item.article_body.is_(None), Item.published_at >= now_utc() - timedelta(days=30),
        ).order_by(Item.published_at.desc()).limit(2)))
        for item in items:
            article_id = urlsplit(item.canonical_url).path.rsplit("/", 1)[-1]
            if not reserve_tool(db):
                stats["budget_exhausted"] = True
                break
            stats["tool_calls"] += 1
            try:
                body = news_body(await call_data(active, catalog, "get_news", {"id": article_id}), article_id)
                item.article_body, item.body_fetched_at = "reader:v2\n" + body, now_utc()
                db.commit()
                stats["bodies_updated"] += 1
            except Exception as exc:
                db.rollback()
                code = error_code(exc)
                stats["errors"][code] = stats["errors"].get(code, 0) + 1


def sync() -> dict:
    if not configured():
        return {"status": "not_configured", "created": 0}
    with SessionLocal() as db:
        if db.scalar(select(Watch.id).where(Watch.watch_id == "gold:london").limit(1)) is None:
            return {"status": "no_gold_subscriptions", "created": 0}
        lease = claim(db)
        if lease is None:
            return {"status": "cached_or_running", "created": 0, "tool_calls": 0}
        run = AgentRun(kind=KIND, status="running", detail="")
        db.add(run)
        db.commit()
        stats = {"status": "success", "entries": 0, "matched": 0, "created": 0,
                 "tool_calls": 0, "budget_exhausted": False, "truncated": False,
                 "dropped": {}, "errors": {}, "bodies_updated": 0}
        try:
            asyncio.run(asyncio.wait_for(collect(db, stats), timeout=100))
        except Exception as exc:
            db.rollback()
            code = error_code(exc)
            stats["errors"][code] = stats["errors"].get(code, 0) + 1
        if stats["errors"]:
            stats["status"] = "partial" if stats["matched"] else "failure"
        if stats["budget_exhausted"]:
            stats["status"] = "partial"
        now = now_utc()
        run = db.get(AgentRun, run.id)
        run.status, run.finished_at, run.item_count = stats["status"], now, stats["created"]
        run.detail = json.dumps(stats, ensure_ascii=False)
        interval = settings.jin10_interval_hours if stats["status"] != "failure" else 2
        db.execute(update(SearchCache).where(SearchCache.key == CACHE_KEY, SearchCache.lease_token == lease).values(
            payload=json.dumps(stats), expires_at=now + timedelta(hours=interval), lease_until=now,
        ))
        db.commit()
        return {"run_id": run.id, **stats}
