WATCHES = {
    "stock:002491": "通鼎互联",
    "stock:002296": "辉煌科技",
    "gold:london": "伦敦金宏观资讯",
    "esports:lol": "英雄联盟",
    "esports:cs2": "CS2",
    "esports:valorant": "无畏契约",
}


def valid_watch(watch_id: str) -> bool:
    return watch_id in WATCHES
