from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from information_agent.agent_tools import news_age_label, scoped_registry
from information_agent.config import settings
from information_agent.db import get_db
from information_agent.domain import WATCHES, resolve_watch_ids, valid_watch
from information_agent.models import AgentRun, Feedback, Item, User, Watch, now_utc
from information_agent.ranking import ranked_items
from information_agent.security import current_user, issue_token, password_hash, password_matches

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
    source_name: str = Field(min_length=2, max_length=120)
    source_type: str = "official"
    published_at: datetime | None = None
    event_key: str | None = Field(default=None, max_length=120)


class AskInput(BaseModel):
    question: str = Field(min_length=3, max_length=300)


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
        "automatic_source": {"gold:london": "美联储货币政策 RSS"},
    }


@router.get("/sources")
def source_status(db: Session = Depends(get_db)) -> dict:
    latest = db.scalar(
        select(AgentRun).where(AgentRun.kind == "fed_rss_sync").order_by(AgentRun.started_at.desc()).limit(1)
    )
    success = db.scalar(
        select(AgentRun)
        .where(AgentRun.kind == "fed_rss_sync", AgentRun.status == "success")
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    )
    return {
        "sources": [
            {
                "id": "fed_monetary_rss",
                "watch_id": "gold:london",
                "label": "美联储货币政策 RSS",
                "status": latest.status if latest else "not_run",
                "last_success_at": success.finished_at.isoformat() if success and success.finished_at else None,
                "last_error": latest.detail if latest and latest.status == "failure" else None,
            }
        ]
    }


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
    if not valid_watch(payload.watch_id):
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
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": ranked_items(db, user.id, limit)}


@router.post("/feedback", status_code=201)
def add_feedback(payload: FeedbackInput, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if payload.action not in {"interested", "not_interested", "duplicate"}:
        raise HTTPException(status_code=422, detail="不支持的反馈动作")
    item = db.get(Item, payload.item_id)
    watched = item is not None and db.scalar(
        select(Watch.id).where(Watch.user_id == user.id, Watch.watch_id == item.watch_id)
    )
    if not watched:
        raise HTTPException(status_code=404, detail="未找到关注范围内的资讯")
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
        summary="",
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


@router.post("/ask")
async def ask(payload: AskInput, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Evidence-only answer until a model provider is explicitly configured."""
    question = payload.question.strip()
    matching = resolve_watch_ids(question)
    supported = bool(matching) or any(word in question for word in ("关注", "资讯", "消息", "新闻", "动态"))
    run = AgentRun(user_id=user.id, kind="evidence_answer", status="running", detail="")
    db.add(run)
    db.commit()
    registry = scoped_registry(user.id)
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

    search_args = {"limit": 5}
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
        "citations": [{"title": item["title"], "url": item["url"]} for item in evidence],
        "run_id": run.id,
        "mode": "evidence_only",
    }
