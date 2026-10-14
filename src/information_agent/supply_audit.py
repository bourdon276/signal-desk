"""Daily aggregate of automatic public search attempts, without user data or article bodies."""

import json
import re
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from information_agent.models import AgentRun, now_utc


def daily_search_summary(db) -> dict:
    local = now_utc().astimezone(ZoneInfo("Asia/Shanghai"))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = list(db.scalars(select(AgentRun).where(
        AgentRun.kind == "web_news_search_sync", AgentRun.user_id.is_(None),
        AgentRun.started_at >= start.astimezone(UTC),
        AgentRun.started_at < (start + timedelta(days=1)).astimezone(UTC),
    ).order_by(AgentRun.started_at).limit(201)))
    result = {"date": start.date().isoformat(), "timezone": "Asia/Shanghai",
              "completed_attempts": 0, "running_attempts": 0, "invalid_records": 0,
              "search_credits": 0, "entries": 0, "matched": 0, "created": 0,
              "dropped": {}, "category_results": {}, "truncated": len(rows) > 200}
    for run in rows[:200]:
        if run.status == "running":
            result["running_attempts"] += 1
            continue
        try:
            detail = json.loads(run.detail)
        except (ValueError, TypeError):
            detail = None
        if not isinstance(detail, dict):
            result["invalid_records"] += 1
            continue
        result["completed_attempts"] += 1
        # Historical records did not store a category; never infer it from a
        # user's subscription or a free-form query.
        category = detail.get("category")
        if category not in {"stock", "index", "team", "gold"}:
            category = "unknown"
        metrics = result["category_results"].setdefault(category, {
            "attempts": 0, "search_credits": 0, "entries": 0, "matched": 0, "created": 0,
        })
        metrics["attempts"] += 1
        for field in ("search_credits", "entries", "matched", "created"):
            value = detail.get(field)
            if type(value) is int and value >= 0:
                result[field] += value
                metrics[field] += value
        dropped = detail.get("dropped")
        if isinstance(dropped, dict):
            for reason, count in dropped.items():
                if (isinstance(reason, str) and re.fullmatch(r"[a-z_]{1,50}", reason)
                        and type(count) is int and count >= 0):
                    result["dropped"][reason] = result["dropped"].get(reason, 0) + count
    return result
