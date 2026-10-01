WATCHES = {
    "stock:002491": "通鼎互联",
    "stock:002296": "辉煌科技",
    "gold:london": "伦敦金宏观资讯",
    "esports:lol": "英雄联盟",
    "esports:cs2": "CS2",
    "esports:valorant": "无畏契约",
}

WATCH_ALIASES = {
    "stock:002491": ("通鼎互联", "通鼎", "002491"),
    "stock:002296": ("辉煌科技", "辉煌", "002296"),
    "gold:london": ("伦敦金", "黄金", "金价", "xauusd"),
    "esports:lol": ("英雄联盟", "lol", "league of legends"),
    "esports:cs2": ("cs2", "counter-strike", "反恐精英"),
    "esports:valorant": ("无畏契约", "valorant", "瓦罗兰特"),
}


def resolve_watch_ids(question: str) -> list[str]:
    normalized = question.lower()
    return [key for key, aliases in WATCH_ALIASES.items() if any(alias in normalized for alias in aliases)]


def valid_watch(watch_id: str) -> bool:
    return watch_id in WATCHES
