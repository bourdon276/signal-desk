"""Fixed public discovery vocabulary; personal feedback never becomes a free-form query."""

from urllib.parse import urlsplit

TEAM_DOMAINS = ["hltv.org", "esportsinsider.com", "dexerto.com", "dotesports.com", "bo3.gg", "teamspirit.gg",
                "dust2.com.br", "news.wmpvp.com", "5eplay.com"]
STOCK_DOMAINS = ["cninfo.com.cn", "eastmoney.com", "10jqka.com.cn", "stcn.com", "cs.com.cn"]
GOLD_DOMAINS = ["eastmoney.com", "10jqka.com.cn", "stcn.com", "cs.com.cn", "kitco.com", "fxstreet.com",
                "bls.gov", "federalreserve.gov", "jin10.com"]
DOMAINS = {"team": TEAM_DOMAINS, "stock": STOCK_DOMAINS, "index": STOCK_DOMAINS, "gold": GOLD_DOMAINS}
FOCUS_BY_KIND = {
    "team": ("interview", "roster"), "stock": ("financial",),
    "index": ("macro", "market"), "gold": ("macro", "gold_market"),
}
FOCUS_LABELS = {
    "recent": "近期综合新闻", "interview": "采访", "roster": "阵容与转会",
    "financial": "财报与业绩", "macro": "宏观经济", "market": "指数与市场动态", "gold_market": "黄金市场",
}


def entity_kind(marker: str) -> str | None:
    if marker == "gold:london":
        return "gold"
    for prefix, kind in (("stock:", "stock"), ("index:", "index"), ("team:cs2:", "team")):
        if marker.startswith(prefix):
            return kind
    return None


def publisher_domain(url: str, kind: str | None) -> str | None:
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
            return None
        host = parts.hostname or ""
    except ValueError:
        return None
    return next((domain for domain in DOMAINS.get(kind, ())
                 if host == domain or host.endswith("." + domain)), None)


def preferred_focus(kind: str | None, profile: dict) -> str:
    allowed = FOCUS_BY_KIND.get(kind, ())
    weights = profile.get("weights", {})
    positive = [focus for focus in allowed if weights.get(focus, 0) > 0]
    if positive:
        return max(positive, key=lambda focus: weights[focus])
    if kind in {"team", "index", "gold"} and any(weights.get(focus, 0) < 0 for focus in allowed):
        alternatives = [focus for focus in allowed if weights.get(focus, 0) >= 0]
        if alternatives:
            return alternatives[0]
    return "recent"


def discovery_plan(kind: str | None, profile: dict) -> dict:
    domains = list(DOMAINS.get(kind, ()))
    avoided = [domain for domain in domains if profile.get("source_weights", {}).get(domain, 0) < 0]
    remaining = [domain for domain in domains if domain not in avoided]
    # Preserve two publishers to avoid turning negative feedback into an empty search.
    fallback = bool(avoided) and len(remaining) < 2
    focus = preferred_focus(kind, profile)
    return {
        "effective_focus": focus, "effective_focus_label": FOCUS_LABELS[focus],
        "search_domains": domains if fallback else remaining,
        "avoided_sources": [] if fallback else avoided, "source_fallback": fallback,
    }
