"""Conservative event grouping; no semantic inference or network calls."""

import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from information_agent.preferences import content_kind


def event_identity(item) -> tuple[str, str]:
    parts = urlsplit(item.canonical_url)
    # Audited Oct 9: PW explicitly attributes this interview to Dust2.br.
    # This is one verified pair, not a general multilingual deduplication model.
    perfect = (
        parts.hostname == "news.wmpvp.com"
        and parts.path == "/news.html"
        and parse_qs(parts.query).get("id") == ["304545"]
        and parse_qs(parts.query).get("gameTypeStr") == ["2"]
    )
    original = parts.hostname == "www.dust2.com.br" and parts.path == (
        "/noticias/78712/donk-temos-a-confianca-de-que-ainda-podemos-vencer-a-pro-league"
    )
    if perfect or original:
        return "verified:dust2-br:78712", "verified_reprint"
    # Exact long titles on the same UTC day and object; short/unknown dates excluded.
    kind = content_kind(item)
    title = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", item.title).casefold()).strip()
    if item.watch_id.startswith("team:cs2:") and kind in {"interview", "team_news", "roster"}:
        if item.published_at is not None and len(title) >= 24:
            stamp = item.published_at
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            key = f"{item.watch_id}|{kind}|{stamp.astimezone(UTC).date()}|{title}"
            return "title:" + hashlib.sha256(key.encode()).hexdigest()[:32], "exact_title_same_day"
    return item.event_key, "stored_event_key"


def story_identity(row: dict) -> str:
    """Presentation-only grouping; never used to expand duplicate feedback scope.

    Require an explicit US indicator, reference month and publication day. Broad
    gold/Fed mentions alone cannot collapse unrelated reports. Corrections remain
    distinct source records inside the timeline.
    """
    if row["watch_id"] != "gold:london" or not row["published_at"]:
        return row["event_key"]
    title = row["title"]
    if not re.search(r"美国|\b(?:US|U\.S\.)\b", title, re.I):
        return row["event_key"]
    indicators = re.findall(r"(?<![a-z])(?:CPI|PPI|PCE)(?![a-z])|非农", title, re.I)
    months = re.findall(r"(?<!\d)(1[0-2]|[1-9])月", title)
    if len(set(x.upper() for x in indicators)) != 1 or len(set(months)) != 1:
        return row["event_key"]
    stamp = datetime.fromisoformat(row['published_at'])
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    day = stamp.astimezone(ZoneInfo("Asia/Shanghai")).date()
    years = set(re.findall(r"(20\d{2})年", title))
    if len(years) > 1:
        return row["event_key"]
    year = next(iter(years)) if years else str(day.year - (int(months[0]) > day.month))
    key = f"us:{indicators[0].upper()}:{year}-{months[0]}:{day}"
    return "macro-story:" + key


def group_rows(rows: list[dict], *, macro_events: bool = False) -> list[dict]:
    """Input must already be scoped and filtered for the user and list window."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(story_identity(row) if macro_events else row["event_key"], []).append(row)
    result = []
    for key, members in groups.items():
        # Prefer current deliveries to backfill; any unread current source stays visible.
        members = sorted(members, key=lambda row: row["published_at"] or "", reverse=True)
        current = [row for row in members if not row.get("is_history")]
        pool = current or members
        primary = next((row for row in pool if not row["is_read"]), pool[0])
        timeline = sorted(members, key=lambda row: row["published_at"] or "", reverse=True)
        result.append(
            {
                **primary,
                "story_key": key,
                "event_group_basis": "macro_indicator_day" if key.startswith("macro-story:")
                else primary["event_group_basis"],
                "source_count": len(members),
                "related_sources": [dict(row) for row in timeline if row["id"] != primary["id"]],
            }
        )
    return result
