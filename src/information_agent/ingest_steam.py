"""Valve-published CS2 news via the documented, public Steam News API."""

import json
import re
from datetime import UTC, datetime

import httpx

from information_agent.config import settings
from information_agent.db import SessionLocal
from information_agent.ingest_common import download, safe_link, store_item
from information_agent.ingest_fed import brief_text
from information_agent.models import AgentRun, now_utc

API_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
KIND = "steam_cs2_sync"
LINK_HOSTS = {"steamstore-a.akamaihd.net", "store.steampowered.com", "steamcommunity.com", "www.counter-strike.net"}


def excerpt(value: str) -> str:
    # Do not render publisher HTML or Steam BBCode in the application.
    value = re.sub(r"\[(?:img|previewyoutube)[^]]*\].*?\[/(?:img|previewyoutube)\]", "", value, flags=re.S | re.I)
    value = re.sub(r"\[/?[^]]+\]", " ", value).replace("\\", " ")
    return brief_text(value)


def sync() -> dict:
    with SessionLocal() as db:
        run = AgentRun(kind=KIND, status="running", detail="")
        db.add(run)
        db.commit()
        try:
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=settings.steam_use_env_proxy) as client:
                data = json.loads(
                    download(
                        client,
                        API_URL,
                        params={
                            "appid": 730,
                            "count": 30,
                            "maxlength": 280,
                            "feeds": "steam_community_announcements",
                        },
                    )
                )
            news = data.get("appnews", {})
            rows = news.get("newsitems")
            if news.get("appid") != 730 or not isinstance(rows, list):
                raise ValueError("unexpected Steam news schema")
            created, skipped = 0, 0
            for row in rows[:30]:
                if not isinstance(row, dict) or row.get("feedname") != "steam_community_announcements":
                    skipped += 1
                    continue
                url = safe_link(str(row.get("url", "")), LINK_HOSTS)
                title = brief_text(str(row.get("title", "")))
                stamp = row.get("date")
                if not url or not title or not isinstance(stamp, int) or not 0 < stamp <= 253402300799:
                    skipped += 1
                    continue
                published = datetime.fromtimestamp(stamp, tz=UTC)
                if published > now_utc():
                    skipped += 1
                    continue
                created += store_item(
                    db,
                    watch_id="esports:cs2",
                    canonical_url=url,
                    title=title,
                    summary=excerpt(str(row.get("contents", ""))),
                    source_name="Valve · Steam",
                    source_type="official",
                    ingestion_mode="api",
                    published_at=published,
                )
            if rows and skipped == len(rows):
                raise ValueError("no valid Steam news rows")
            run.status = "success"
            run.item_count = created
            run.detail = json.dumps({"entries": len(rows), "skipped": skipped})
            run.finished_at = now_utc()
            db.commit()
            return {"run_id": run.id, "created": created, "entries": len(rows)}
        except Exception as exc:
            db.rollback()
            run.status = "failure"
            run.detail = type(exc).__name__  # Never persist request URLs or credentials from exception strings.
            run.finished_at = now_utc()
            db.add(run)
            db.commit()
            raise RuntimeError("Steam news sync failed; existing items retained") from None


if __name__ == "__main__":
    print(sync())
