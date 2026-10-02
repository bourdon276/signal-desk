"""Public source registry and user-scoped coverage. Never exposes subscription lists."""

import json
import re
from datetime import UTC, timedelta

from sqlalchemy import select

from information_agent.ingest_cninfo import PREFIX, configured
from information_agent.models import AgentRun, Item, now_utc
from information_agent.personalization import candidate_filter, matches, user_scope

SOURCE_SPECS = [
    {
        "id": "fed_monetary_rss",
        "kind": "fed_rss_sync",
        "watch_id": "gold:london",
        "label": "美联储宏观",
        "automatic": True,
        "description": "货币政策 RSS；不包含实时金价。",
    },
    {
        "id": "steam_cs2",
        "kind": "steam_cs2_sync",
        "watch_id": "esports:cs2",
        "label": "CS2 官方更新",
        "automatic": True,
        "description": "Valve · Steam 新闻 API；版本与官方活动，不覆盖全部战队赛事。",
    },
    {
        "id": "stock_announcements",
        "kind": None,
        "watch_id": "stocks",
        "label": "股票公告",
        "automatic": configured(),
        "description": "官方 API 已配置；仅查询订阅代码，近14天最多100条。"
        if configured()
        else "现有历史收录可读；自动公告接口等待账号授权与展示许可。",
    },
    {
        "id": "riot_manual",
        "kind": None,
        "watch_id": "esports:riot",
        "label": "英雄联盟 / 无畏契约",
        "automatic": False,
        "description": "目前为人工核对收录，尚无自动更新来源。",
    },
]


def state(db, kind: str | None, automatic: bool) -> dict:
    condition = AgentRun.kind == kind if kind else AgentRun.kind.startswith(PREFIX, autoescape=True)
    latest = (
        db.scalar(select(AgentRun).where(condition).order_by(AgentRun.started_at.desc()).limit(1))
        if automatic
        else None
    )
    success = (
        db.scalar(
            select(AgentRun)
            .where(condition, AgentRun.status == "success")
            .order_by(AgentRun.started_at.desc())
            .limit(1)
        )
        if automatic
        else None
    )
    status = latest.status if latest else "not_run" if automatic else "not_configured"
    stamp = latest.started_at if latest else None
    if stamp is not None and stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    if automatic and stamp and now_utc() - stamp > timedelta(hours=8 if kind and kind.startswith(PREFIX) else 2):
        status = "stale"
    return {
        "status": status,
        "last_success_at": success.finished_at.isoformat() if success and success.finished_at else None,
        "last_attempt_at": latest.started_at.isoformat() if latest else None,
        "last_error": "最近采集未成功，已有消息保留。" if latest and latest.status == "failure" else None,
    }


def public_sources(db):
    return [
        {**{k: v for k, v in spec.items() if k != "kind"}, **state(db, spec["kind"], spec["automatic"])}
        for spec in SOURCE_SPECS
    ]


def coverage(db, user_id):
    enabled, topics = user_scope(db, user_id)
    rows = list(
        db.scalars(
            select(Item)
            .where(candidate_filter(enabled, topics))
            .order_by(Item.published_at.desc().nulls_last(), Item.created_at.desc())
            .limit(500)
        )
    )
    topic_by_id = {t.id: t for t in topics}
    result = []
    for watch_id in sorted(enabled):
        topic = topic_by_id.get(watch_id)
        terms = json.loads(topic.keywords) if topic else []
        code = (
            watch_id[6:]
            if re.fullmatch(r"stock:[0-9]{6}", watch_id)
            else next((t[6:] for t in terms if re.fullmatch(r"stock:[0-9]{6}", t)), None)
        )
        found = [r for r in rows if watch_id in matches(r, enabled, topics)]
        automatic_found = any(r.ingestion_mode in {"rss", "api"} for r in found)
        if code:
            auto = configured()
            source = state(db, PREFIX + code, auto)
            note = (
                "自动公告近14天最多100条，不提供实时行情。"
                if auto
                else "已保存股票代码；自动公告需配置数据服务账号与展示许可。"
            )
        elif watch_id in {"gold:london", "esports:cs2"}:
            spec = next(s for s in SOURCE_SPECS if s["watch_id"] == watch_id)
            auto, source, note = True, state(db, spec["kind"], True), spec["description"]
        else:
            auto = automatic_found
            source = {"status": "library_filter", "last_success_at": None, "last_attempt_at": None, "last_error": None}
            note = (
                "关键词持续匹配新入库消息；尚未匹配到自动来源。"
                if not auto
                else "关键词已匹配自动入库消息；只覆盖当前来源，不保证新消息持续命中。"
            )
            if watch_id in {"esports:lol", "esports:valorant"}:
                note = "历史收录可读；该游戏尚无自动来源。"
        latest = next((r.published_at.isoformat() for r in found if r.published_at), None)
        result.append(
            {
                "watch_id": watch_id,
                "automatic": auto,
                "matched_count": len(found),
                "count_limit": 500,
                "latest_item_at": latest,
                "description": note,
                **source,
            }
        )
    return result
