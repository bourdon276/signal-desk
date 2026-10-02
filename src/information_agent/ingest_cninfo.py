"""Prepared official announcement adapter; disabled until token and display rights are configured.

Uses the publisher's p_info3015 metadata contract. No PDF/body requests.
No authorized response has yet been available for integration acceptance.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from threading import Lock
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select, text

from information_agent.config import settings
from information_agent.db import SessionLocal
from information_agent.ingest_common import download, safe_link, store_item
from information_agent.ingest_fed import brief_text
from information_agent.models import AgentRun, Topic, Watch, now_utc

API_URL = "https://webapi.cninfo.com.cn/api/info/p_info3015"
PREFIX = "cninfo_stock_"
LOCK = Lock()
LINK_HOSTS = {
    "static.cninfo.com.cn",
    "www.cninfo.com.cn",
    "dataclouds.cninfo.com.cn",
    "disc.static.szse.cn",
    "reportdocs.static.szse.cn",
}


def configured() -> bool:
    return bool(settings.cninfo_access_token.get_secret_value()) and settings.cninfo_display_allowed


def stock_codes(db) -> list[str]:
    codes = set()
    ids = db.scalars(select(Watch.watch_id).distinct())
    for watch_id in ids:
        if re.fullmatch(r"stock:[0-9]{6}", watch_id):
            codes.add(watch_id[6:])
    topics = db.scalars(select(Topic).join(Watch, (Watch.watch_id == Topic.id) & (Watch.user_id == Topic.user_id)))
    for topic in topics:
        for keyword in json.loads(topic.keywords):
            if re.fullmatch(r"stock:[0-9]{6}", keyword):
                codes.add(keyword[6:])
    return sorted(codes)


def reserve(db, code: str):
    # Reserve before network I/O so failed and interrupted attempts consume budget.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(734021)"))
    now = now_utc()
    start = now.astimezone(ZoneInfo("Asia/Shanghai")).replace(hour=0, minute=0, second=0, microsecond=0)
    count = db.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(
            AgentRun.kind.startswith(PREFIX, autoescape=True),
            AgentRun.started_at >= start,
        )
    )
    latest = db.scalar(
        select(AgentRun).where(AgentRun.kind == PREFIX + code).order_by(AgentRun.started_at.desc()).limit(1)
    )
    if count >= settings.cninfo_daily_request_limit:
        db.rollback()
        return None
    if latest:
        stamp = latest.started_at.replace(tzinfo=UTC) if latest.started_at.tzinfo is None else latest.started_at
        if now - stamp < timedelta(hours=6):
            db.rollback()
            return None
    run = AgentRun(kind=PREFIX + code, status="running", detail="")
    db.add(run)
    db.commit()
    return run


def sync() -> dict:
    if not configured():
        return {"status": "not_configured", "created": 0}
    created, attempted, failed = 0, 0, 0
    with LOCK, SessionLocal() as db:
        codes = stock_codes(db)
        # Oldest requested stock first prevents one popular code consuming all budget.
        last = {
            code: db.scalar(select(func.max(AgentRun.started_at)).where(AgentRun.kind == PREFIX + code))
            for code in codes
        }
        codes.sort(key=lambda code: (last[code] is not None, str(last[code] or ""), code))
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            for code in codes[:20]:
                run = reserve(db, code)
                if run is None:
                    continue
                attempted += 1
                try:
                    today = now_utc().astimezone(ZoneInfo("Asia/Shanghai")).date()
                    result = json.loads(
                        download(
                            client,
                            API_URL,
                            method="POST",
                            data={
                                "access_token": settings.cninfo_access_token.get_secret_value(),
                                "scode": code,
                                "sdate": str(today - timedelta(days=14)),
                                "edate": str(today),
                                "format": "json",
                                "page": 1,
                                "pagesize": 100,
                                "@orderby": "F001D:desc",
                            },
                        )
                    )
                    if str(result.get("resultcode")) != "200" or not isinstance(result.get("records"), list):
                        raise ValueError("announcement API rejected request or changed schema")
                    rows = result["records"]
                    added, skipped = 0, 0
                    for row in rows[:100]:
                        if not isinstance(row, dict) or str(row.get("SECCODE")) != code:
                            skipped += 1
                            continue
                        url = safe_link(str(row.get("F003V", "")), LINK_HOSTS)
                        title = brief_text(str(row.get("F002V", "")))
                        if not url or not title:
                            skipped += 1
                            continue
                        published = datetime.fromisoformat(str(row.get("F001D", "")))
                        if published.tzinfo is None:
                            published = published.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                        if published > now_utc():
                            skipped += 1
                            continue
                        company = brief_text(str(row.get("SECNAME", "")))
                        added += store_item(
                            db,
                            watch_id="stock:" + code,
                            canonical_url=url,
                            title=f"{company}：{title}"[:500] if company else title,
                            summary="",
                            source_name="巨潮资讯",
                            source_type="official",
                            ingestion_mode="api",
                            published_at=published,
                        )
                    if rows and skipped == len(rows):
                        raise ValueError("no valid announcement rows")
                    run.status = "success"
                    run.item_count = added
                    run.detail = json.dumps(
                        {
                            "entries": len(rows),
                            "skipped": skipped,
                            "window_days": 14,
                            "possibly_truncated": len(rows) >= 100,
                        }
                    )
                    created += added
                    run.finished_at = now_utc()
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    run.status = "failure"
                    run.detail = type(exc).__name__
                    run.finished_at = now_utc()
                    db.add(run)
                    db.commit()
                    failed += 1
                    # Rejected credentials/rights should not fan out paid calls to other stocks.
                    break
    return {"created": created, "attempted": attempted, "failed": failed}
