"""Allowlisted, non-personal evidence for the collection observation window."""

import json
import os
import re
from collections import Counter
from datetime import UTC, timedelta

from sqlalchemy import select

from information_agent.models import AgentRun, Item, now_utc

SOURCE_KEYS = {
    "fed", "gold_jin10", "cs2_team_matches", "cs2_team_news", "dust2_br_news",
    "perfect_world_news", "stock_announcements", "web_news", "article_bodies",
}
COUNTERS = {
    "entries", "matched", "created", "updated", "attempted", "failed", "prepared",
    "tool_calls", "search_credits", "bodies_updated", "skipped", "deferred_targets",
}
STATUSES = {
    "success", "partial", "failure", "running", "not_configured", "no_gold_subscriptions",
    "cached_or_running", "budget_exhausted", "skipped", "not_run",
}


def stamp(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def safe_source(value):
    if not isinstance(value, dict):
        return {"status": "unknown"}
    result = {"status": value.get("status") if value.get("status") in STATUSES else "unknown"}
    for key in COUNTERS:
        count = value.get(key)
        if type(count) is int and count >= 0:
            result[key] = count
    # No nested errors, free-text messages, URLs, queries, entity names or tokens.
    return result


def snapshot(db, days=7):
    end = now_utc()
    start = end - timedelta(days=days)
    runs = list(db.scalars(select(AgentRun).where(
        AgentRun.kind == "scheduled_collection", AgentRun.user_id.is_(None),
        AgentRun.started_at >= start, AgentRun.started_at < end,
    ).order_by(AgentRun.started_at, AgentRun.id).limit(2001)))
    records = []
    for run in runs[:2000]:
        try:
            detail = json.loads(run.detail or "{}")
        except (TypeError, ValueError):
            detail = None
        valid = isinstance(detail, dict)
        deployed = detail.get("_deployment_commit") if valid else None
        records.append({
            "deployed_commit": deployed
            if isinstance(deployed, str) and re.fullmatch(r"[a-f0-9]{40}", deployed) else None,
            "id": run.id, "status": run.status if run.status in STATUSES else "unknown",
            "started_at": stamp(run.started_at).isoformat(),
            "finished_at": stamp(run.finished_at).isoformat() if run.finished_at else None,
            "duration_ms": round((stamp(run.finished_at) - stamp(run.started_at)).total_seconds() * 1000)
            if run.finished_at and stamp(run.finished_at) >= stamp(run.started_at) else None,
            "detail_valid": valid,
            "sources": {key: safe_source(value) for key, value in detail.items() if key in SOURCE_KEYS}
            if valid else {},
        })
    # Select metadata only, not bodies or reading/feedback/user tables.
    items = db.execute(select(
        Item.created_at, Item.published_at, Item.ingestion_mode,
        Item.article_body.is_not(None).label("body_cached"),
    ).where(Item.created_at >= start, Item.created_at < end)
        .order_by(Item.created_at, Item.id).limit(5001)).all()
    counts = Counter()
    delays = []
    for item in items[:5000]:
        counts["inserted_records"] += 1
        counts["body_cached_records"] += int(item.body_cached)
        if item.ingestion_mode not in {"rss", "api"}:
            counts["non_provider_dated_records"] += 1
            continue
        if not item.published_at:
            counts["missing_publication_time"] += 1
            continue
        delay = (stamp(item.created_at) - stamp(item.published_at)).total_seconds()
        if delay < 0:
            counts["future_publication_time"] += 1
        elif delay > 86400:
            counts["backfill_over_24h"] += 1
        else:
            delays.append(round(delay, 3))
    commit = os.environ.get("RENDER_GIT_COMMIT", "")
    return {
        "schema": "collection-observation-v1", "captured_at": end.isoformat(),
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "deployed_commit": commit if re.fullmatch(r"[a-f0-9]{40}", commit) else None,
        "runs": records, "runs_truncated": len(runs) > 2000,
        "inventory": {"counts": dict(counts), "truncated": len(items) > 5000,
                      "rss_api_insert_delay_seconds_within_24h": sorted(delays)},
        "limitations": [
            "Collection execution is not source recall, answer accuracy or service uptime.",
            "Delay sample excludes search-estimated dates, missing/future dates and backfill over 24h.",
            "Delay sample can include initial imports within 24h; not steady-state latency.",
            "Cached body presence is not evidence that the full body is accurate or readable.",
            "Overlapping inventory snapshots must not be summed. Runs can be deduplicated by id.",
        ],
    }
