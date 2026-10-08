"""Explainable content facets and bounded, user-scoped preference events."""

import re

from information_agent.news_quality import is_prediction

REASONS = {"content_type", "source", "hide_only"}
KIND_LABELS = {
    "game_update": "版本更新",
    "match": "比赛赛程与结果",
    "roster": "阵容与转会",
    "interview": "采访",
    "financial": "财报与业绩",
    "governance": "公司治理公告",
    "stock_notice": "其他股票公告",
    "team_news": "战队新闻",
    "prediction": "赛事预测与赔率",
    "other": "其他资讯",
}


def content_kind(item) -> str:
    # Only titles and trusted provider identity; do not treat article instructions as rules.
    text = item.title.casefold()
    if item.source_name == "PandaScore · CS2 赛事数据":
        return "match"
    if item.watch_id.startswith("stock:"):
        if re.search(r"年度报告|半年度报告|季度报告|财报|业绩|financial|earnings", text):
            return "financial"
        if re.search(r"董事会|监事会|股东大会|公司章程|治理|board meeting", text):
            return "governance"
        return "stock_notice"
    if (item.watch_id.startswith("team:cs2:") or "战队新闻" in item.source_name) and is_prediction(item.title):
        return "prediction"
    if item.source_name == "Valve · Steam" or re.search(r"patch notes|counter-strike 2 update|版本更新|更新日志", text):
        return "game_update"
    # Publisher interview headlines often use Speaker: "quote" without the word interview.
    if re.search(r"\binterviews?\b|采访|专访|[:：]\s*[\"“]", text):
        return "interview"
    if re.search(r"\b(roster|transfer|signs?|benched|joins?|departs?|lineup)\b|转会|阵容|离队|加盟", text):
        return "roster"
    if "战队新闻" in item.source_name or item.watch_id.startswith("team:"):
        return "team_news"
    return "other"


def preference_key(item, reason):
    # Unknown free-text legacy reasons retain their original watch-wide semantics.
    if reason == "content_type":
        kind = content_kind(item)
        # No broad learning from an unclassified article.
        return ("kind", kind) if kind != "other" else None
    if reason == "source":
        return ("source", item.source_name)
    return None
