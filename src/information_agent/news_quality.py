"""Conservative title rules for team news, shared by discovery and reading."""

import re

PREDICTION_TITLE = re.compile(
    r"\b(?:odds|betting|bets|bookmakers?|predictions?|apostas?|palpites?|prognósticos?)\b|赔率|投注|博彩|赛前预测",
    re.I,
)


def is_prediction(title: str) -> bool:
    return bool(PREDICTION_TITLE.search(title))


def news_exclusion(title: str, watch_id: str, source_name: str) -> str | None:
    if source_name == "PandaScore · CS2 赛事数据":
        return None
    if (watch_id.startswith("team:cs2:") or "战队新闻" in source_name) and is_prediction(title):
        return "prediction_or_betting"
    return None
