"""Deterministic query boundaries; model instructions cannot override these."""

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

PRIVATE_DENIAL = "无权访问其他用户的关注列表、阅读记录或私人数据。你可以查询自己关注对象的公开资讯。"


def requests_other_users(question: str) -> bool:
    other = re.search(r"其他用户|其它用户|别的用户|他人|别人|another user|other users?", question, re.I)
    private = re.search(
        r"关注列表|阅读记录|私人|隐私|账户|账号|邮箱|watchlist|reading history|private|email", question, re.I
    )
    return bool(other and private)


def query_window(question: str) -> tuple[datetime | None, datetime | None]:
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).replace(hour=0, minute=0, second=0, microsecond=0)
    if "今天" in question or re.search(r"\btoday\b", question, re.I):
        return today.astimezone(UTC), (today + timedelta(days=1)).astimezone(UTC)
    if "昨天" in question:
        return (today - timedelta(days=1)).astimezone(UTC), today.astimezone(UTC)
    explicit = re.search(r"(?:近|过去|最近)\s*(\d{1,3})\s*天", question)
    if re.search(r"(?:最近|近|过去)\s*(?:一个|一|1)?月", question):
        return now - timedelta(days=30), now
    days = min(90, max(1, int(explicit.group(1)))) if explicit else 30
    if not explicit and any(word in question for word in ("本周", "这周")):
        days = 7
    if explicit or any(word in question for word in ("最近", "近期", "本周", "这周")):
        end = now + timedelta(days=7) if any(word in question for word in ("赛程", "待赛", "即将")) else now
        return now - timedelta(days=days), end
    return None, None


def display_title(title: str, source_name: str) -> str:
    # Old stored fixtures also need correction before the next provider sync.
    if source_name == "PandaScore · CS2 赛事数据" and title.endswith(" · 赛程"):
        title = re.sub(r"\s+\d+\s*:\s*\d+\s+", " vs ", title)
        return "待赛：" + title.removesuffix(" · 赛程")
    return title
