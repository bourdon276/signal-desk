"""Public source registry and user-scoped coverage. Never exposes subscription lists."""

import json
import re
from datetime import UTC, timedelta

from sqlalchemy import select

from information_agent.ingest_cninfo import PREFIX, configured
from information_agent.ingest_pandascore import KIND as PANDASCORE_KIND
from information_agent.ingest_pandascore import configured as pandascore_configured
from information_agent.models import AgentRun, Item, now_utc
from information_agent.personalization import candidate_filter, matches, user_scope

SOURCE_SPECS = [
    {
        "id": "cs2_team_news",
        "kind": "cs2_team_news_sync",
        "watch_id": "esports:cs2",
        "label": "CS2 战队新闻",
        "automatic": True,
        "description": "Esports Insider Counter-Strike RSS；按战队及少量选手别名匹配标题/短摘录，只展示标题与原文链接。订阅窗口有限，不保证每个战队都有新消息。",
    },
    {
        "id": "fed_monetary_rss",
        "kind": "fed_rss_sync",
        "watch_id": "gold:london",
        "label": "美联储宏观",
        "automatic": True,
        "description": "货币政策 RSS；不包含实时金价。",
    },
    {
        "id": "cs2_team_fixtures",
        "kind": PANDASCORE_KIND,
        "watch_id": "esports:cs2",
        "label": "CS2 战队赛程与结果",
        "automatic": pandascore_configured(),
        "description": "PandaScore CS2 fixtures API；覆盖战队赛程、状态与公开比分，不包括战队公告和完整赛事新闻。",
    },
    {
        "id": "steam_cs2_archive",
        "kind": None,
        "watch_id": "esports:cs2",
        "label": "CS2 游戏公告（低优先级）",
        "automatic": False,
        "description": "仅保留已有的 Valve 游戏版本/活动收录；不再作为战队资讯来源持续采集。",
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
            .where(condition, AgentRun.status.in_(("success", "partial")))
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
    result = {
        "status": status,
        "last_success_at": success.finished_at.isoformat() if success and success.finished_at else None,
        "last_attempt_at": latest.started_at.isoformat() if latest else None,
        "last_error": "最近采集未成功，已有消息保留。" if latest and latest.status == "failure" else None,
    }
    if kind in {PANDASCORE_KIND, "cs2_team_news_sync"}:
        metrics = None
        if latest and latest.status in {"success", "partial"}:
            try:
                detail = json.loads(latest.detail)
            except (TypeError, ValueError):
                detail = None
            if isinstance(detail, dict):
                fields = (
                    "entries",
                    "teams",
                    "resolved_teams",
                    "unresolved_teams",
                    "matches",
                    "matched",
                    "created",
                    "updated",
                    "skipped",
                    "full_pages",
                )
                metrics = {field: detail[field] for field in fields if isinstance(detail.get(field), int)}
                dropped = detail.get("dropped")
                if isinstance(dropped, dict):
                    metrics["dropped"] = {
                        str(reason): count
                        for reason, count in dropped.items()
                        if isinstance(count, int)
                    }
        result["last_result"] = metrics
    return result


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
        elif watch_id == "gold:london":
            spec = next(s for s in SOURCE_SPECS if s["watch_id"] == watch_id)
            auto, source, note = True, state(db, spec["kind"], True), spec["description"]
        elif watch_id == "esports:cs2":
            auto = pandascore_configured()
            source = state(db, PANDASCORE_KIND, auto)
            note = (
                "请添加具体 CS2 战队；配置 PandaScore Token 后才会同步该战队赛程与赛果。"
                if not auto
                else "CS2 通用主题不代表已关注具体战队；请添加战队名称以接收其赛程与赛果。"
            )
        elif topic and any(term.startswith("team:cs2:") for term in terms):
            auto = pandascore_configured()
            source = state(db, PANDASCORE_KIND, auto)
            note = (
                "已保存 CS2 战队关注；等待 PandaScore 私密 API Token。配置后同步赛程、比分，不等同于战队新闻。"
                if not auto
                else "PandaScore 提供赛程/比分；Esports Insider RSS 补充战队相关新闻索引，窗口与匹配范围有限。"
            )
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
