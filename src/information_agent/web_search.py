"""Search-backed discovery: bounded public entity queries, shared cache and credit caps."""

import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from information_agent.config import settings
from information_agent.db import SessionLocal
from information_agent.domain import WATCHES
from information_agent.entities import canonical_team_name, is_team_watch_id
from information_agent.ingest_common import safe_link, store_item
from information_agent.ingest_fed import brief_text
from information_agent.ingest_team_news import mentions_team
from information_agent.models import AgentRun, Item, SearchBudget, SearchCache, Topic, Watch, now_utc
from information_agent.personalization import user_scope
from information_agent.search_provider import configured, provider

KIND = "web_news_search_sync"
FOCUSES = {"recent", "roster", "interview", "financial"}
TEAM_DOMAINS = ["esportsinsider.com", "dexerto.com", "dotesports.com", "bo3.gg", "teamspirit.gg"]
STOCK_DOMAINS = ["cninfo.com.cn", "eastmoney.com", "10jqka.com.cn", "stcn.com", "cs.com.cn"]


def targets(db, user_id: str | None = None) -> dict[str, dict]:
    """Expose selectable subscription IDs, but search only their canonical public entities."""
    if user_id is None:
        enabled = set(db.scalars(select(Watch.watch_id)))
        topics = list(
            db.scalars(select(Topic).join(Watch, (Watch.watch_id == Topic.id) & (Watch.user_id == Topic.user_id)))
        )
    else:
        enabled, topics = user_scope(db, user_id)
    result = {}
    for marker in sorted(enabled):
        if re.fullmatch(r"stock:[0-9]{6}", marker):
            result[marker] = {"watch_id": marker, "name": WATCHES.get(marker, marker[6:]), "kind": "stock"}
    for topic in topics:
        for marker in json.loads(topic.keywords):
            if re.fullmatch(r"stock:[0-9]{6}", marker):
                result[topic.id] = {"watch_id": marker, "name": WATCHES.get(marker, marker[6:]), "kind": "stock"}
            elif is_team_watch_id(marker):
                slug = marker.removeprefix("team:cs2:")
                # Recover public names from canonical IDs, never send private custom labels.
                if re.fullmatch(r"[0-9a-f]{16}", slug):
                    continue
                result[topic.id] = {
                    "watch_id": marker,
                    "name": canonical_team_name(slug.replace("-", " ")),
                    "kind": "team",
                }
    return result


def request_spec(target: dict, focus: str) -> tuple[str, list[str]]:
    name = re.sub(r"[^\w .-]", " ", target["name"])[:60]
    if target["kind"] == "stock":
        query = f"{name} {target['watch_id'][6:]} 股票 公司 公告 财报 新闻"
        return query, STOCK_DOMAINS
    suffix = {"roster": "roster transfer", "interview": "interview", "recent": "news", "financial": "news"}[focus]
    return f'"{name}" Counter-Strike CS2 {suffix}', TEAM_DOMAINS


def timestamp(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return stamp.astimezone(UTC) if stamp.tzinfo else None


def normalize_result(row, target, domains, now):
    if not isinstance(row, dict):
        return None, "invalid_result"
    url = row.get("url")
    if not isinstance(url, str):
        return None, "invalid_url"
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return None, "invalid_url"
    # Boundary-aware publisher subdomains, never arbitrary destinations or redirects.
    hosts = {host} if any(host == d or host.endswith("." + d) for d in domains) else set()
    url = safe_link(url, hosts)
    if not url:
        return None, "unapproved_url"
    parts = urlsplit(url)
    query = [
        (k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_") and k not in {"fbclid", "gclid"}
    ]
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    title = brief_text(row.get("title", ""))[:500] if isinstance(row.get("title"), str) else ""
    excerpt = brief_text(row.get("content", ""))[:360] if isinstance(row.get("content"), str) else ""
    if not title:
        return None, "missing_title"
    stamp = timestamp(row.get("published_date"))
    if stamp is None or not now - timedelta(days=30) <= stamp <= now:
        return None, "missing_or_outside_date"
    text = title + " " + excerpt
    if target["kind"] == "stock":
        code = target["watch_id"][6:]
        matched = re.search(r"(?<!\d)" + code + r"(?!\d)", text)
        known_name = WATCHES.get(target["watch_id"])
        if not matched and not (known_name and known_name in text):
            return None, "entity_mismatch"
    else:
        if not mentions_team(text, target["name"]):
            return None, "entity_mismatch"
        if not re.search(r"\bcs2\b|counter[ -]strike|\bdonk\b|\bsh1ro\b|反恐精英", text, re.I):
            return None, "missing_cs2_context"
    # Provider excerpts and estimated dates are not verified article bodies.
    return {
        "watch_id": target["watch_id"],
        "canonical_url": url,
        "title": title,
        "summary": "搜索摘录（未核验全文；日期为搜索服务估计）：" + (excerpt or "仅有标题，请打开原文核对。"),
        "source_name": host + (" · 战队新闻" if target["kind"] == "team" else " · 股票资讯"),
        "source_type": "media",
        "ingestion_mode": "search",
        "published_at": stamp,
    }, None


def _aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def claim(key: str, user_id: str | None):
    now, token = now_utc(), str(uuid.uuid4())
    with SessionLocal() as db:
        insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        db.execute(
            insert(SearchCache)
            .values(key=key, payload="{}", expires_at=now, lease_until=now, lease_token="")
            .on_conflict_do_nothing(index_elements=["key"])
        )
        cache = db.get(SearchCache, key)
        if _aware(cache.expires_at) > now:
            result = json.loads(cache.payload)
            db.commit()
            return {**result, "cache_hit": True, "search_credits": 0}, None
        changed = db.execute(
            update(SearchCache)
            .where(SearchCache.key == key, SearchCache.lease_until <= now, SearchCache.expires_at <= now)
            .values(lease_until=now + timedelta(seconds=30), lease_token=token)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            db.rollback()
            return {"status": "busy", "results": [], "search_credits": 0}, None
        today = now.astimezone(ZoneInfo("Asia/Shanghai"))
        scopes = [
            ("month:" + today.strftime("%Y-%m"), settings.search_month_credit_limit),
            ("day:" + today.strftime("%Y-%m-%d"), settings.search_day_credit_limit),
        ]
        if user_id:
            scopes.append(("user:" + user_id + ":" + today.strftime("%Y-%m-%d"), settings.search_user_day_limit))
        for scope, cap in scopes:
            db.execute(
                insert(SearchBudget).values(scope=scope, credits=0).on_conflict_do_nothing(index_elements=["scope"])
            )
            changed = db.execute(
                update(SearchBudget)
                .where(SearchBudget.scope == scope, SearchBudget.credits < cap)
                .values(credits=SearchBudget.credits + 1)
            )
            if changed.rowcount != 1:
                db.rollback()
                return {"status": "budget_exhausted", "results": [], "search_credits": 0}, None
        db.commit()
    return None, token


async def discover(target: dict, focus: str = "recent", user_id: str | None = None) -> dict:
    if not configured():
        return {"status": "not_configured", "results": [], "search_credits": 0}
    if focus not in FOCUSES:
        return {"status": "unsupported_focus", "results": [], "search_credits": 0}
    query, domains = request_spec(target, focus)
    adapter = provider()
    key = hashlib.sha256(json.dumps([adapter.cache_namespace, target["watch_id"], query, domains]).encode()).hexdigest()
    cached, token = claim(key, user_id)
    if cached is not None:
        return cached
    # Reservations count attempted requests, including uncertain failures; no automatic retries.
    with SessionLocal() as db:
        run = AgentRun(user_id=user_id, kind=KIND, status="running", detail="")
        db.add(run)
        db.commit()
        run_id = run.id
    result = {"status": "failure", "results": [], "search_credits": 1, "cache_hit": False}
    try:
        rows = await asyncio.wait_for(adapter.search(query, domains), timeout=15)
        dropped, ids, created = {}, [], 0
        with SessionLocal() as db:
            for row in rows:
                values, reason = normalize_result(row, target, domains, now_utc())
                if reason:
                    dropped[reason] = dropped.get(reason, 0) + 1
                    continue
                created += int(store_item(db, **values))
                item = db.scalar(
                    select(Item).where(
                        Item.canonical_url == values["canonical_url"], Item.watch_id == target["watch_id"]
                    )
                )
                if item:
                    ids.append(item.id)
                else:
                    dropped["url_owned_by_other_entity"] = dropped.get("url_owned_by_other_entity", 0) + 1
            db.commit()
        result.update(
            status="success",
            results=list(dict.fromkeys(ids)),
            entries=len(rows),
            matched=len(set(ids)),
            created=created,
            dropped=dropped,
        )
    except asyncio.CancelledError:
        result["error_type"] = "cancelled"
        raise
    except Exception as exc:
        # Never persist provider response bodies, API keys or request headers.
        result["error_type"] = type(exc).__name__
    finally:
        with SessionLocal() as db:
            now = now_utc()
            db.execute(
                update(SearchCache)
                .where(SearchCache.key == key, SearchCache.lease_token == token)
                .values(
                    payload=json.dumps(result),
                    expires_at=now + timedelta(hours=settings.search_cache_hours)
                    if result["status"] == "success"
                    else now + timedelta(minutes=5),
                    lease_until=now,
                )
            )
            run = db.get(AgentRun, run_id)
            run.status = result["status"]
            run.item_count = len(result["results"])
            run.finished_at = now
            run.detail = json.dumps({k: v for k, v in result.items() if k != "results"})
            db.commit()
    return result


def sync() -> dict:
    if not configured():
        return {"status": "not_configured", "search_credits": 0}
    with SessionLocal() as db:
        unique = {value["watch_id"]: value for value in targets(db).values()}
        today = now_utc().astimezone(ZoneInfo("Asia/Shanghai"))
        used = db.get(SearchBudget, "day:" + today.strftime("%Y-%m-%d"))
        # Daily deterministic rotation avoids starving later subscriptions under a small global cap.
        remaining = max(0, settings.search_day_credit_limit - (used.credits if used else 0))
    ordered = sorted(
        unique.values(), key=lambda r: hashlib.sha256((today.strftime("%Y-%m-%d") + r["watch_id"]).encode()).hexdigest()
    )
    results = []
    for target in ordered[: min(remaining, 10)]:
        results.append(asyncio.run(discover(target)))
        if results[-1]["status"] == "budget_exhausted":
            break
    return {"status": "completed", "targets": len(results), "search_credits": sum(r["search_credits"] for r in results)}


if __name__ == "__main__":
    print(sync())
