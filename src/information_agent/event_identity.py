"""Conservative event grouping; no semantic inference or network calls."""

import hashlib
import re
import unicodedata
from datetime import UTC
from urllib.parse import parse_qs, urlsplit

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


def group_rows(rows: list[dict]) -> list[dict]:
    """Input must already be scoped and filtered for the user and list window."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["event_key"], []).append(row)
    result = []
    for members in groups.values():
        # Preserve ranking; if any source is unread, show an unread representative.
        primary = next((row for row in members if not row["is_read"]), members[0])
        result.append(
            {
                **primary,
                "source_count": len(members),
                "related_sources": [
                    {k: row[k] for k in ("id", "title", "url", "source_name", "published_at", "is_read")}
                    for row in members
                    if row["id"] != primary["id"]
                ],
            }
        )
    return result
