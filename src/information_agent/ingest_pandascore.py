"""CS2 team fixtures and results from PandaScore's documented REST API."""

import json
from datetime import UTC, datetime
from threading import Lock
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from information_agent.config import settings
from information_agent.db import SessionLocal
from information_agent.entities import canonical_team_name, is_team_watch_id, normalize_entity_name
from information_agent.ingest_common import download, safe_link, store_item
from information_agent.models import AgentRun, Item, Topic, Watch, now_utc

API_ROOT = "https://api.pandascore.co/csgo"
KIND = "pandascore_cs2_sync"
LOCK = Lock()
LINK_HOSTS = {"www.pandascore.co", "pandascore.co"}
MATCH_STATES = {
    "not_started": "赛程",
    "running": "进行中",
    "finished": "赛果",
}


def configured() -> bool:
    return bool(settings.pandascore_token.get_secret_value())


def watched_teams(db) -> dict[str, str]:
    topics = db.scalars(
        select(Topic).join(Watch, (Watch.watch_id == Topic.id) & (Watch.user_id == Topic.user_id))
    )
    result = {}
    for topic in topics:
        for marker in json.loads(topic.keywords):
            if is_team_watch_id(marker):
                result.setdefault(marker, canonical_team_name(topic.name))
    return result


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None:
        return None
    return result.astimezone(UTC)


def _score_by_team(match: dict) -> dict[str, int]:
    results = match.get("results")
    if not isinstance(results, list):
        return {}
    return {
        str(row["team_id"]): int(row["score"])
        for row in results
        if isinstance(row, dict) and row.get("team_id") is not None and isinstance(row.get("score"), int)
    }


def _match_item(match: dict, watch_id: str, followed_name: str) -> dict | None:
    opponents = match.get("opponents")
    if not isinstance(opponents, list):
        return None
    team_entries = [
        entry.get("opponent")
        for entry in opponents
        if isinstance(entry, dict) and isinstance(entry.get("opponent"), dict)
    ]
    followed_key = normalize_entity_name(followed_name)
    followed = next(
        (team for team in team_entries if normalize_entity_name(str(team.get("name", ""))) == followed_key),
        None,
    )
    if followed is None:
        return None
    other = next((team for team in team_entries if team.get("id") != followed.get("id")), None)
    opponent_name = str(other.get("name", "對手")) if other else "待定對手"
    status = str(match.get("status", "not_started"))
    label = MATCH_STATES.get(status, "比賽")
    scores = _score_by_team(match)
    followed_score = scores.get(str(followed.get("id")))
    opponent_score = scores.get(str(other.get("id"))) if other else None
    if followed_score is not None and opponent_score is not None:
        title = f"{followed_name} {followed_score} : {opponent_score} {opponent_name} · {label}"
    else:
        title = f"{followed_name} vs {opponent_name} · {label}"

    when = parse_timestamp(match.get("scheduled_at")) or parse_timestamp(match.get("begin_at"))
    if status == "finished":
        when = parse_timestamp(match.get("end_at")) or parse_timestamp(match.get("begin_at")) or when
    if when is None or when > now_utc() and status != "not_started":
        return None

    tournament = match.get("tournament")
    tournament_name = str(tournament.get("name", "")) if isinstance(tournament, dict) else ""
    shanghai_time = when.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M 北京时间")
    details = [f"比赛状态：{label}。", f"PandaScore 记录的比赛时间：{shanghai_time}。"]
    if tournament_name:
        details.append(f"赛事：{tournament_name}。")
    if status == "finished" and followed_score is not None and opponent_score is not None:
        details.append(f"比分：{followed_name} {followed_score} : {opponent_score} {opponent_name}。")
    elif status == "not_started":
        details.append("这是赛事赛程，不代表战队新闻或实时直播信息。")

    original = safe_link(str(match.get("url", "")), LINK_HOSTS)
    slug = match.get("slug")
    url = original or (safe_link(f"https://www.pandascore.co/csgo/matches/{slug}", LINK_HOSTS) if slug else None)
    if not url:
        return None
    return {
        "watch_id": watch_id,
        "canonical_url": url,
        "title": title[:500],
        "summary": " ".join(details)[:500],
        "source_name": "PandaScore · CS2 赛事数据",
        "source_type": "other",
        "ingestion_mode": "api",
        "published_at": when,
    }


def _fetch_matches(client: httpx.Client, path: str, token: str) -> list[dict]:
    payload = json.loads(
        download(
            client,
            f"{API_ROOT}/matches/{path}",
            params={
                "per_page": 100,
                "sort": "-begin_at" if path == "past" else "begin_at",
                "filter[videogame_title]": "cs-2",
            },
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        )
    )
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ValueError("unexpected PandaScore response schema")
    return payload[:100]


def sync() -> dict:
    if not configured():
        return {"status": "not_configured", "created": 0}
    with LOCK, SessionLocal() as db:
        teams = watched_teams(db)
        if not teams:
            return {"status": "no_team_subscriptions", "created": 0}
        run = AgentRun(kind=KIND, status="running", detail="")
        db.add(run)
        db.commit()
        try:
            token = settings.pandascore_token.get_secret_value()
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
                matches = []
                for state in ("upcoming", "running", "past"):
                    matches.extend(_fetch_matches(client, state, token))
            # Deduplicate API rows if a provider briefly returns the same match in two lifecycle lists.
            rows_by_id = {str(row.get("id") or row.get("slug")): row for row in matches}
            created, updated, skipped = 0, 0, 0
            for marker, team_name in teams.items():
                for match in rows_by_id.values():
                    values = _match_item(match, marker, team_name)
                    if values is None:
                        continue
                    existing = db.scalar(select(Item).where(Item.canonical_url == values["canonical_url"]))
                    if existing is None:
                        created += store_item(db, **values)
                    elif existing.watch_id == marker and (
                        existing.title != values["title"] or existing.summary != values["summary"]
                    ):
                        existing.title = values["title"]
                        existing.summary = values["summary"]
                        existing.published_at = values["published_at"]
                        updated += 1
                    elif existing.watch_id != marker:
                        skipped += 1
            run.status = "success"
            run.item_count = created + updated
            run.detail = json.dumps(
                {"teams": len(teams), "matches": len(rows_by_id), "updated": updated, "skipped": skipped}
            )
            run.finished_at = now_utc()
            db.commit()
            return {"run_id": run.id, "created": created, "updated": updated, "matches": len(rows_by_id)}
        except Exception as exc:
            db.rollback()
            run.status = "failure"
            run.detail = type(exc).__name__
            run.finished_at = now_utc()
            db.add(run)
            db.commit()
            raise RuntimeError("PandaScore sync failed; existing items retained") from None


if __name__ == "__main__":
    print(sync())
