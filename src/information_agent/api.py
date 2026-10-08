from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import re
from datetime import datetime
from time import perf_counter
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from information_agent import model_agent
from information_agent.agent_tools import SearchNews, news_age_label, scoped_registry
from information_agent.config import settings
from information_agent.db import get_db
from information_agent.domain import WATCHES, resolve_watch_ids, valid_watch
from information_agent.entities import canonical_team_name, is_team_watch_id, team_watch_id
from information_agent.models import AgentRun, Feedback, Item, Reading, Topic, User, Watch, now_utc
from information_agent.personalization import matches, user_scope
from information_agent.query_policy import PRIVATE_DENIAL, query_window, requests_other_users
from information_agent.ranking import ranked_items
from information_agent.search_provider import configured as search_configured
from information_agent.security import current_user, issue_token, password_hash, password_matches
from information_agent.sources import coverage, public_sources
from information_agent.sync_worker import request_sync
from information_agent.web_search import FOCUSES

router = APIRouter(prefix="/api")


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=10, max_length=128)


class Registration(Credentials):
    invite_code: str | None = None


class WatchInput(BaseModel):
    watch_id: str
    enabled: bool


class FeedbackInput(BaseModel):
    item_id: str
    action: str
    reason: str | None = Field(default=None, max_length=120)


class ManualItemInput(BaseModel):
    watch_id: str
    url: HttpUrl
    title: str = Field(min_length=3, max_length=500)
    summary: str = Field(default="", max_length=500)
    source_name: str = Field(min_length=2, max_length=120)
    source_type: str = "official"
    published_at: datetime | None = None
    event_key: str | None = Field(default=None, max_length=120)


class AskInput(BaseModel):
    question: str = Field(min_length=3, max_length=300)
    use_model: bool = False
    use_search: bool = False


class SearchInput(BaseModel):
    watch_id: str = Field(min_length=1, max_length=64)
    focus: str = "recent"


class TopicInput(BaseModel):
    name: str = Field(default="", max_length=60)
    keywords: list[str] = Field(default_factory=list, max_length=5)
    stock_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    team_name: str | None = Field(default=None, min_length=2, max_length=60)


class ReadingInput(BaseModel):
    item_id: str
    read: bool


@router.get("/topics")
def list_topics(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(Topic).where(Topic.user_id == user.id).order_by(Topic.created_at))
    return {
        "topics": [
            {
                "id": t.id,
                "name": t.name,
                "keywords": json.loads(t.keywords),
                "stock_code": next((k[6:] for k in json.loads(t.keywords) if re.fullmatch(r"stock:[0-9]{6}", k)), None),
                "team_name": t.name if any(is_team_watch_id(k) for k in json.loads(t.keywords)) else None,
                "team_watch_id": next((k for k in json.loads(t.keywords) if is_team_watch_id(k)), None),
            }
            for t in rows
        ]
    }


@router.post("/topics", status_code=201)
def create_topic(payload: TopicInput, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if payload.stock_code and payload.team_name:
        raise HTTPException(status_code=422, detail="一次只能创建一种对象关注")
    if payload.stock_code:
        name = payload.name.strip() or f"股票 {payload.stock_code}"
        keywords = [f"stock:{payload.stock_code}"]
    elif payload.team_name:
        name = payload.name.strip() or payload.team_name.strip()
        keywords = [team_watch_id(payload.team_name)]
    else:
        name = payload.name.strip()
        keywords = list(dict.fromkeys(term.strip() for term in payload.keywords))
    if (
        len(name) < 2
        or not keywords
        or any(not 2 <= len(term) <= 64 for term in keywords)
        or (not payload.stock_code and not payload.team_name and any(len(term) > 40 for term in keywords))
    ):
        raise HTTPException(status_code=422, detail="请输入有效的股票代码或战队名称")
    owned = list(db.scalars(select(Topic).where(Topic.user_id == user.id)))
    if len(owned) >= 20:
        raise HTTPException(status_code=422, detail="最多添加 20 个自定义关注")
    if any(t.name == name or set(json.loads(t.keywords)).intersection(keywords) for t in owned):
        raise HTTPException(status_code=409, detail="该关注名称已存在")
    topic = Topic(user_id=user.id, name=name, keywords=json.dumps(keywords, ensure_ascii=False))
    db.add(topic)
    db.flush()
    db.add(Watch(user_id=user.id, watch_id=topic.id))
    db.commit()
    sync_queued = False
    if settings.sync_in_web and payload.stock_code:
        sync_queued = request_sync("stock_announcements")
    elif settings.sync_in_web and payload.team_name:
        sync_queued = request_sync("cs2_team_matches")
        request_sync("cs2_team_news")
    if settings.sync_in_web and search_configured():
        sync_queued = request_sync("web_news") or sync_queued
    return {
        "id": topic.id,
        "name": topic.name,
        "keywords": keywords,
        "team_name": canonical_team_name(payload.team_name) if payload.team_name else None,
        "team_watch_id": keywords[0] if payload.team_name else None,
        "stock_code": payload.stock_code,
        "sync_queued": sync_queued,
    }


@router.put("/reading")
def set_reading(payload: ReadingInput, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(Item, payload.item_id)
    enabled, topics = user_scope(db, user.id)
    if item is None or not matches(item, enabled, topics):
        raise HTTPException(status_code=404, detail="未找到关注范围内的资讯")
    existing = db.scalar(select(Reading).where(Reading.user_id == user.id, Reading.item_id == item.id))
    if payload.read and existing is None:
        db.add(Reading(user_id=user.id, item_id=item.id))
    elif not payload.read and existing is not None:
        db.delete(existing)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"item_id": item.id, "read": payload.read}


def normalize_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname:
        raise HTTPException(status_code=422, detail="只接受 HTTPS 原文链接")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", parts.netloc.lower(), path, parts.query, ""))


def require_admin(token: str | None) -> None:
    if not settings.admin_token or token is None or not hmac.compare_digest(token, settings.admin_token):
        raise HTTPException(status_code=403, detail="无管理权限")


@router.get("/catalog")
def catalog() -> dict:
    return {
        "watches": [{"id": key, "name": value} for key, value in WATCHES.items()],
        "automatic_source": {"gold:london": "美联储货币政策 RSS", "team:cs2": "PandaScore CS2 赛程与结果"},
    }


@router.get("/sources")
def source_status(db: Session = Depends(get_db)) -> dict:
    return {"sources": public_sources(db)}


@router.get("/coverage")
def watch_coverage(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"coverage": coverage(db, user.id)}


@router.post("/register", status_code=201)
def register(payload: Registration, db: Session = Depends(get_db)) -> dict:
    if settings.registration_code and payload.invite_code != settings.registration_code:
        raise HTTPException(status_code=403, detail="邀请码不正确")
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="邮箱格式不正确")
    user = User(email=email, password_hash=password_hash(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="邮箱已注册") from None
    return {"token": issue_token(user.id), "user": {"id": user.id, "email": user.email}}


@router.post("/login")
def login(payload: Credentials, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or not password_matches(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    return {"token": issue_token(user.id), "user": {"id": user.id, "email": user.email}}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id, "email": user.email}


@router.get("/watches")
def list_watches(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    ids = list(db.scalars(select(Watch.watch_id).where(Watch.user_id == user.id)))
    return {"watch_ids": ids}


@router.put("/watches")
def update_watch(payload: WatchInput, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if (
        not valid_watch(payload.watch_id)
        and db.scalar(select(Topic.id).where(Topic.id == payload.watch_id, Topic.user_id == user.id)) is None
    ):
        raise HTTPException(status_code=422, detail="未知关注对象")
    existing = db.scalar(select(Watch).where(Watch.user_id == user.id, Watch.watch_id == payload.watch_id))
    if payload.enabled and existing is None:
        db.add(Watch(user_id=user.id, watch_id=payload.watch_id))
    elif not payload.enabled and existing is not None:
        db.delete(existing)
    db.commit()
    return {"watch_id": payload.watch_id, "enabled": payload.enabled}


@router.get("/feed")
def feed(
    view: Literal["news", "matches", "all"] = "news",
    watch_id: str | None = Query(default=None, max_length=64),
    news_kind: Literal["all", "interview", "roster", "financial"] = "all",
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    diagnostics = {}
    items = ranked_items(db, user.id, limit, view=view, watch_id=watch_id, news_kind=news_kind, diagnostics=diagnostics)
    return {
        "items": items,
        "view": view,
        "watch_id": watch_id,
        "news_kind": news_kind,
        "recent_days": 30,
        "upcoming_days": 7,
        "diagnostics": diagnostics,
    }


@router.post("/feedback", status_code=201)
def add_feedback(payload: FeedbackInput, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if payload.action not in {"interested", "not_interested", "duplicate"}:
        raise HTTPException(status_code=422, detail="不支持的反馈动作")
    item = db.get(Item, payload.item_id)
    enabled, topics = user_scope(db, user.id)
    watched = item is not None and matches(item, enabled, topics)
    if not watched:
        raise HTTPException(status_code=404, detail="未找到关注范围内的资讯")
    if payload.reason not in {None, "content_type", "source", "hide_only"}:
        raise HTTPException(status_code=422, detail="请选择内容类型、来源或仅隐藏本条")
    if payload.action == "duplicate" and payload.reason is not None:
        raise HTTPException(status_code=422, detail="重复消息不支持偏好原因")
    event = Feedback(user_id=user.id, item_id=item.id, action=payload.action, reason=payload.reason)
    db.add(event)
    db.commit()
    return {"id": event.id, "action": event.action, "created_at": event.created_at.isoformat()}


@router.get("/feedback")
def list_feedback(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    events = list(
        db.scalars(select(Feedback).where(Feedback.user_id == user.id).order_by(Feedback.created_at.desc()).limit(100))
    )
    return {
        "events": [
            {
                "id": e.id,
                "item_id": e.item_id,
                "action": e.action,
                "reason": e.reason,
                "created_at": e.created_at.isoformat(),
                "undone_at": e.undone_at.isoformat() if e.undone_at else None,
            }
            for e in events
        ]
    }


@router.post("/feedback/{feedback_id}/undo")
def undo_feedback(feedback_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    event = db.scalar(select(Feedback).where(Feedback.id == feedback_id, Feedback.user_id == user.id))
    if event is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    if event.undone_at is None:
        event.undone_at = now_utc()
        db.commit()
    return {"id": event.id, "undone": True}


@router.post("/admin/items", status_code=201)
def add_manual_item(
    payload: ManualItemInput,
    x_admin_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    require_admin(x_admin_token)
    if not valid_watch(payload.watch_id):
        raise HTTPException(status_code=422, detail="未知关注对象")
    if payload.source_type not in {"official", "media", "community", "other"}:
        raise HTTPException(status_code=422, detail="无效来源类型")
    url = normalize_url(str(payload.url))
    existing = db.scalar(select(Item).where(Item.canonical_url == url))
    if existing is not None:
        return {"id": existing.id, "created": False}
    event_key = payload.event_key or hashlib.sha256(url.encode()).hexdigest()[:32]
    item = Item(
        watch_id=payload.watch_id,
        canonical_url=url,
        title=payload.title.strip(),
        summary=payload.summary.strip(),
        source_name=payload.source_name.strip(),
        source_type=payload.source_type,
        ingestion_mode="manual_link",
        event_key=event_key,
        published_at=payload.published_at,
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "created": True}


@router.get("/admin/runs")
def list_runs(
    x_admin_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    require_admin(x_admin_token)
    rows = list(db.scalars(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(50)))
    return {
        "runs": [
            {
                "id": run.id,
                "kind": run.kind,
                "status": run.status,
                "item_count": run.item_count,
                "detail": run.detail,
                "started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "duration_ms": round((run.finished_at - run.started_at).total_seconds() * 1000)
                if run.finished_at
                else None,
            }
            for run in rows
        ]
    }


@router.get("/agent/status")
def agent_status() -> dict:
    return {
        "configured": model_agent.configured(),
        "model": settings.model_name if model_agent.configured() else None,
        "max_rounds": model_agent.MAX_ROUNDS,
        "max_tools": model_agent.MAX_TOOLS,
        "search_max_rounds": model_agent.SEARCH_MAX_ROUNDS,
        "search_configured": search_configured(),
        "search_day_credit_limit": settings.search_day_credit_limit,
        "search_month_credit_limit": settings.search_month_credit_limit,
    }


@router.post("/search")
async def search_news(payload: SearchInput, user: User = Depends(current_user)) -> dict:
    if payload.focus not in FOCUSES:
        raise HTTPException(status_code=422, detail="无效搜索类别")
    return await SearchNews(user.id, None, None).execute(payload.watch_id, payload.focus)


@router.get("/runs/{run_id}")
def my_run(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    run = db.get(AgentRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return {"id": run.id, "kind": run.kind, "status": run.status, "trace": json.loads(run.detail or "{}")}


@router.post("/ask")
async def ask(payload: AskInput, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Evidence-only answer until a model provider is explicitly configured."""
    if requests_other_users(payload.question):
        run = AgentRun(
            user_id=user.id,
            kind="policy_denial",
            status="success",
            detail=json.dumps({"reason": "private_data_request", "tools": [], "model_calls": 0, "model_cost_cny": 0}),
            finished_at=now_utc(),
        )
        db.add(run)
        db.commit()
        return {"answer": PRIVATE_DENIAL, "citations": [], "run_id": run.id, "mode": "permission_denied"}
    if payload.use_model and model_agent.configured():
        run = AgentRun(user_id=user.id, kind="model_agent", status="running", detail="")
        db.add(run)
        db.commit()
        trace = {}
        reserved = None
        try:
            enabled, topics = user_scope(db, user.id)
            names = {t.id: t.name for t in topics}
            watches = [{"id": key, "name": names.get(key, WATCHES.get(key, key))} for key in sorted(enabled)]
            reserved = model_agent.reserve(user.id, allow_search=payload.use_search and search_configured())
            trace["reserved_cost_cny"] = reserved[1] / 1_000_000
            result = await asyncio.wait_for(
                model_agent.run(
                    payload.question,
                    user.id,
                    watches,
                    trace,
                    allow_search=payload.use_search and search_configured(),
                ),
                timeout=40,
            )
            if not trace.get("usage_unknown"):
                actual = math.ceil(trace["estimated_cost_cny"] * 1_000_000)
                model_agent.settle(*reserved, actual)
                trace["budget_charged_cny"] = actual / 1_000_000
            else:
                trace["budget_charged_cny"] = reserved[1] / 1_000_000
            run.status = "success"
            run.detail = json.dumps(trace, ensure_ascii=False)
            run.finished_at = now_utc()
            run.item_count = len(result["citations"])
            db.commit()
            return {**result, "run_id": run.id}
        except Exception as exc:
            # Failed/uncertain calls retain their reservation; do not assume upstream refunded them.
            trace["error_type"] = type(exc).__name__
            trace["fallback_reason"] = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            trace["budget_charged_cny"] = reserved[1] / 1_000_000 if reserved else 0
            run.status = "failure"
            run.detail = json.dumps(trace, ensure_ascii=False)
            run.finished_at = now_utc()
            db.commit()
            fallback = await ask(AskInput(question=payload.question), user, db)
            reason = trace["fallback_reason"]
            reason_text = {
                "output_truncated": "模型回答超过长度限制",
                "invalid_answer_json": "模型回答格式不符合要求",
                "invalid_citation": "模型引用未通过校验",
                "missing_inline_citation": "模型引用标记不完整",
                "tool_limit": "模型工具调用超过限制",
                "context_limit": "检索上下文超过限制",
                "budget_exhausted": "今日调用次数或费用预算已达上限",
                "request_budget": "单次预算不足",
                "TimeoutError": "模型处理超时",
                "ReadTimeout": "模型服务响应超时",
                "HTTPStatusError": "模型服务返回错误",
            }.get(reason, "模型流程未完成")
            fallback.update(
                {"mode": "model_fallback", "model_run_id": run.id, "notice": reason_text + "，已回退为已入库证据检索。"}
            )
            return fallback
    question = payload.question.strip()
    matching = resolve_watch_ids(question)
    personal = db.scalars(select(Topic).where(Topic.user_id == user.id))
    matching.extend(
        t.id
        for t in personal
        if t.name.casefold() in question.casefold()
        or any(k.startswith("stock:") and k[6:] in question for k in json.loads(t.keywords))
    )
    supported = bool(matching) or any(word in question for word in ("关注", "资讯", "消息", "新闻", "动态"))
    run = AgentRun(user_id=user.id, kind="evidence_answer", status="running", detail="")
    db.add(run)
    db.commit()
    since, until = query_window(question)
    registry = scoped_registry(user.id, since, until)
    trace = []

    async def execute_tool(name: str, arguments: dict):
        started = perf_counter()
        result = await registry.execute(name, arguments)
        failed = isinstance(result, str)
        trace.append(
            {
                "tool": name,
                "arguments": arguments,
                "status": "failure" if failed else "success",
                "duration_ms": round((perf_counter() - started) * 1000),
                "result_count": len(result) if isinstance(result, list) else int(result is not None and not failed),
            }
        )
        if failed:
            raise RuntimeError(f"{name} failed")
        return result

    wants_matches = any(word in question for word in ("比赛", "赛程", "赛果", "比分", "待赛"))
    wants_news = any(word in question for word in ("新闻", "消息", "资讯"))
    search_args = {
        "limit": 5,
        "view": "all" if wants_matches and wants_news else "matches" if wants_matches else "news",
    }
    if matching:
        search_args["watch_ids"] = matching
    try:
        found = await execute_tool("search_items", search_args) if supported else []
        if not isinstance(found, list):
            raise RuntimeError("search_items returned an error")
        evidence = []
        for row in found:
            detail = await execute_tool("get_evidence", {"item_id": row["id"]})
            if isinstance(detail, dict) and "url" in detail:
                evidence.append(detail)
    except Exception as exc:
        run.status = "failure"
        run.detail = json.dumps(
            {"tools": trace, "error_type": type(exc).__name__, "model_tokens": 0, "model_cost_cny": 0},
            ensure_ascii=False,
        )
        run.finished_at = now_utc()
        db.commit()
        raise HTTPException(status_code=503, detail="证据检索暂时不可用") from None
    if not supported:
        answer = "当前仅支持查询关注对象的已收录资讯，例如“通鼎互联和 CS2 最近有什么消息？”。暂不支持其他问题。"
    elif evidence:
        lines = ["当前已入库的相关消息："]
        for item in evidence:
            lines.append(f"• {item['title']}（{item['source_name']}，{news_age_label(item['published_at'])}）")
        lines.append("以上按个人反馈和时间排序，仅覆盖已收录的来源记录。")
        answer = "\n".join(lines)
    else:
        answer = "目前你的关注范围内没有可引用的已入库消息。这不代表外部没有新消息，可能是来源尚未接入或同步失败。"
    run.status = "success"
    run.item_count = len(evidence)
    run.detail = json.dumps(
        {"tools": trace, "watch_ids": matching or "all", "model_tokens": 0, "model_cost_cny": 0}, ensure_ascii=False
    )
    run.finished_at = now_utc()
    db.commit()
    return {
        "answer": answer,
        "citations": [
            {"title": item["title"], "url": item["url"], "source_name": item["source_name"]} for item in evidence
        ],
        "run_id": run.id,
        "mode": "evidence_only",
    }
