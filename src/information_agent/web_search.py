"""Search-backed discovery: bounded public entity queries, shared cache and credit caps."""

import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from information_agent.acquisition_preferences import acquisition_profile
from information_agent.config import settings
from information_agent.db import SessionLocal
from information_agent.discovery_policy import GOLD_DOMAINS, discovery_plan
from information_agent.discovery_policy import STOCK_DOMAINS as STOCK_DOMAINS
from information_agent.discovery_policy import TEAM_DOMAINS as TEAM_DOMAINS
from information_agent.domain import INDEX_NAMES, STOCK_NAMES
from information_agent.entities import canonical_team_name, is_team_watch_id
from information_agent.gold_news import GOLD_FOCUSES, gold_reason, kind_matches
from information_agent.ingest_common import safe_link, store_item
from information_agent.ingest_eastmoney import article_url as eastmoney_url
from information_agent.ingest_eastmoney import read_article as read_eastmoney
from information_agent.ingest_fed import brief_text
from information_agent.ingest_team_news import mentions_team
from information_agent.models import AgentRun, Item, SearchBudget, SearchCache, Topic, Watch, now_utc
from information_agent.news_quality import news_exclusion
from information_agent.personalization import user_scope
from information_agent.preferences import content_kind
from information_agent.search_provider import configured, provider
from information_agent.search_schedule import automatic_due_at, fair_order

KIND = "web_news_search_sync"
FOCUSES = {"auto", "recent", "roster", "interview", "financial", "macro", "market"} | GOLD_FOCUSES
SEARCH_POLICY_VERSION = "entity-news-v8-gold-source-preferences"


def targets(db, user_id: str | None = None) -> dict[str, dict]:
    """Expose selectable subscription IDs, but search only their canonical public entities."""
    if user_id is None:
        enabled = set(db.scalars(select(Watch.watch_id)))
        topics = list(
            db.scalars(select(Topic).join(Watch, (Watch.watch_id == Topic.id) & (Watch.user_id == Topic.user_id)))
        )
    else:
        enabled, topics = user_scope(db, user_id)
    result = {}
    for marker in sorted(enabled):
        if marker == "gold:london":
            result[marker] = {"watch_id": marker, "name": "spot gold XAUUSD", "kind": "gold"}
        elif re.fullmatch(r"stock:[0-9]{6}", marker):
            result[marker] = {"watch_id": marker, "name": STOCK_NAMES.get(marker[6:], marker[6:]), "kind": "stock"}
        elif marker in INDEX_NAMES:
            result[marker] = {"watch_id": marker, "name": INDEX_NAMES[marker], "kind": "index"}
    for topic in topics:
        for marker in json.loads(topic.keywords):
            if re.fullmatch(r"stock:[0-9]{6}", marker):
                result[topic.id] = {
                    "watch_id": marker, "name": STOCK_NAMES.get(marker[6:], marker[6:]), "kind": "stock",
                }
            elif marker in INDEX_NAMES:
                result[topic.id] = {"watch_id": marker, "name": INDEX_NAMES[marker], "kind": "index"}
            elif is_team_watch_id(marker):
                slug = marker.removeprefix("team:cs2:")
                # Recover public names from canonical IDs, never send private custom labels.
                if re.fullmatch(r"[0-9a-f]{16}", slug):
                    continue
                result[topic.id] = {
                    "watch_id": marker,
                    "name": canonical_team_name(slug.replace("-", " ")),
                    "kind": "team",
                }
    return result


def request_spec(target: dict, focus: str) -> tuple[str, list[str]]:
    name = re.sub(r"[^\w .-]", " ", target["name"])[:60]
    if target["kind"] == "gold":
        # Macro releases need not mention gold in the publisher headline.
        query = {
            "macro": "美国 CPI PPI PCE 非农 美联储 美元指数 新闻",
            "macro_data": "美国 CPI PPI PCE 非农 经济数据 公布",
            "policy": "美联储 官员 讲话 利率 决议 Fed FOMC",
            "gold_opinion": "黄金 机构 分析师 展望 gold analyst outlook",
        }.get(focus, "spot gold XAUUSD market news")
        domains = GOLD_DOMAINS
    elif target["kind"] in {"stock", "index"}:
        suffix = {
            "financial": "财报 业绩", "macro": "宏观 经济 政策 新闻", "market": "市场 动态 新闻",
        }.get(focus, "新闻")
        query = (f"{name} {suffix}" if target["kind"] == "index"
                 else f"{name} {target['watch_id'].rsplit(':', 1)[-1]} {suffix}")
        domains = STOCK_DOMAINS
    else:
        suffix = {"roster": "roster transfer", "interview": "interview"}.get(focus, "news")
        query, domains = f"{name} CS2 {suffix}", TEAM_DOMAINS
    # Internal plans may narrow an allowlist, never widen it or supply arbitrary hosts.
    narrowed = [domain for domain in domains if domain in target.get("search_domains", domains)]
    return query, narrowed if len(narrowed) >= 2 else list(domains)


def timestamp(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    if stamp.tzinfo is None:
        # A provider date without a time is usable only as an estimated calendar date.
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return None
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC)


def normalize_result(row, target, domains, now):
    if not isinstance(row, dict):
        return None, "invalid_result"
    url = row.get("url")
    if not isinstance(url, str):
        return None, "invalid_url"
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return None, "invalid_url"
    # Boundary-aware publisher subdomains, never arbitrary destinations or redirects.
    hosts = {host} if any(host == d or host.endswith("." + d) for d in domains) else set()
    url = safe_link(url, hosts)
    if not url:
        return None, "unapproved_url"
    parts = urlsplit(url)
    if target["kind"] in {"stock", "index", "gold"} and (
        host == "quote.eastmoney.com" or (host == "egs.stcn.com" and parts.path.startswith("/quotation/"))
    ):
        return None, "not_news_article"
    query = [
        (k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_") and k not in {"fbclid", "gclid"}
    ]
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    title = brief_text(row.get("title", ""))[:500] if isinstance(row.get("title"), str) else ""
    excerpt = brief_text(row.get("content", ""))[:360] if isinstance(row.get("content"), str) else ""
    if not title:
        return None, "missing_title"
    stamp = timestamp(row.get("published_date"))
    # Approved Eastmoney article paths embed the publisher's calendar date.
    # This is an estimated date, not a verified article timestamp.
    if stamp is None and (host == "eastmoney.com" or host.endswith(".eastmoney.com")):
        date_match = re.fullmatch(r"/a/(\d{8})\d+\.html", parts.path)
        if date_match:
            try:
                stamp = datetime.strptime(date_match[1], "%Y%m%d").replace(
                    tzinfo=ZoneInfo("Asia/Shanghai")
                ).astimezone(UTC)
            except ValueError:
                pass
    if stamp is None:
        return None, "missing_date"
    if not now - timedelta(days=30) <= stamp <= now:
        return None, "outside_30_days"
    text = title + " " + excerpt
    if target["kind"] == "gold":
        identity_text = text + (" BLS" if host in {"bls.gov", "www.bls.gov"} else "")
        if not gold_reason(identity_text):
            return None, "entity_mismatch"
        # A gold keyword on a shop, quote or jewellery page is not market reporting.
        article_path = (
            bool(re.match(r"^/news/(?:\d{4}-\d{2}-\d{2}/|article/)", parts.path))
            if host == "kitco.com" or host.endswith(".kitco.com") else
            bool(re.match(r"^/news/[^/]+-\d{10,}", parts.path))
            if host == "fxstreet.com" or host.endswith(".fxstreet.com") else
            bool(re.fullmatch(r"/news\.release/archives/(?:cpi|ppi|empsit|jolts)_\d{8}\.htm", parts.path))
            if host in {"bls.gov", "www.bls.gov"} else
            bool(re.fullmatch(r"/newsevents/(?:pressreleases|speech)/[^/]+\.htm", parts.path))
            if host in {"federalreserve.gov", "www.federalreserve.gov"} else
            bool(re.search(r"\d{6,}", parts.path))
        )
        if not article_path:
            return None, "not_news_article"
        if re.search(r"首饰|珠宝|金店|回收报价|今日金店|gold jewellery|gold jewelry", title, re.I):
            return None, "not_gold_market_news"
    elif target["kind"] in {"stock", "index"}:
        code = target["watch_id"].rsplit(":", 1)[-1]
        matched = re.search(r"(?<!\d)" + code + r"(?!\d)", text)
        known_name = target["name"] if target["name"] != code else None
        if code == "000001":
            # SZ stock and SH index share six digits: a code alone is ambiguous.
            identity = (
                r"上证(?:综合)?指数|上证综指" if target["kind"] == "index"
                else r"平安银行|(?:SZ|深圳)\s*000001|000001\s*\.SZ"
            )
            if not re.search(identity, text, re.I):
                return None, "entity_mismatch"
        if not matched and not (known_name and known_name in text):
            return None, "entity_mismatch"
    else:
        excluded = news_exclusion(title, target["watch_id"], "战队新闻")
        if excluded:
            return None, excluded
        if not mentions_team(text, target["name"]):
            return None, "entity_mismatch"
        hltv = host == "hltv.org" or host.endswith(".hltv.org")
        if hltv and not re.match(r"^/news/\d+/", parts.path):
            return None, "not_news_article"
        cs2_section = hltv or bool(re.match(r"^/(?:cs2|csgo)/(?:news|articles)/", parts.path, re.I))
        if not cs2_section and not re.search(r"\bcs2\b|counter[ -]strike|\bdonk\b|\bsh1ro\b|反恐精英", text, re.I):
            return None, "missing_cs2_context"
    # Provider excerpts and estimated dates are not verified article bodies.
    return {
        "watch_id": target["watch_id"],
        "canonical_url": url,
        "title": title,
        "summary": excerpt or "",
        "source_name": host + ({"team": " · 战队新闻", "gold": " · 黄金资讯"}.get(
            target["kind"], " · 股票资讯",
        )),
        "source_type": "official" if host in {"bls.gov", "www.bls.gov", "federalreserve.gov",
                                              "www.federalreserve.gov"} else "media",
        "ingestion_mode": "search",
        "published_at": stamp,
    }, None


def _aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def rejection_detail(row, reason: str, domains: list[str]) -> dict:
    """Bounded public metadata only; never retain snippets or unapproved destinations."""
    title, url, stamp = "结果格式不完整", None, None
    if isinstance(row, dict):
        if isinstance(row.get("title"), str):
            title = brief_text(row["title"]) or "无标题"
        stamp = timestamp(row.get("published_date"))
        if isinstance(row.get("url"), str):
            try:
                parts = urlsplit(row["url"])
                host = parts.hostname or ""
                if any(host == d or host.endswith("." + d) for d in domains):
                    # Strip tracking/auth query parameters even for approved publishers.
                    url = safe_link(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), {host})
            except ValueError:
                pass
    return {"title": title, "url": url, "reason": reason, "published_at": stamp.isoformat() if stamp else None}


def claim(key: str, user_id: str | None):
    now, token = now_utc(), str(uuid.uuid4())
    with SessionLocal() as db:
        insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        db.execute(
            insert(SearchCache)
            .values(key=key, payload="{}", expires_at=now, lease_until=now, lease_token="")
            .on_conflict_do_nothing(index_elements=["key"])
        )
        cache = db.get(SearchCache, key)
        if _aware(cache.expires_at) > now:
            result = json.loads(cache.payload)
            db.commit()
            return {**result, "cache_hit": True, "search_credits": 0}, None
        changed = db.execute(
            update(SearchCache)
            .where(SearchCache.key == key, SearchCache.lease_until <= now, SearchCache.expires_at <= now)
            .values(lease_until=now + timedelta(seconds=30), lease_token=token)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            db.rollback()
            return {"status": "busy", "results": [], "search_credits": 0}, None
        today = now.astimezone(ZoneInfo("Asia/Shanghai"))
        scopes = [
            ("month:" + today.strftime("%Y-%m"), settings.search_month_credit_limit),
            ("day:" + today.strftime("%Y-%m-%d"), settings.search_day_credit_limit),
        ]
        if user_id:
            scopes.append(("user:" + user_id + ":" + today.strftime("%Y-%m-%d"), settings.search_user_day_limit))
        else:
            scopes.append(("auto_day:" + today.strftime("%Y-%m-%d"), automatic_day_cap()))
        for scope, cap in scopes:
            db.execute(
                insert(SearchBudget).values(scope=scope, credits=0).on_conflict_do_nothing(index_elements=["scope"])
            )
            changed = db.execute(
                update(SearchBudget)
                .where(SearchBudget.scope == scope, SearchBudget.credits < cap)
                .values(credits=SearchBudget.credits + 1)
            )
            if changed.rowcount != 1:
                db.rollback()
                return {"status": "budget_exhausted", "results": [], "search_credits": 0}, None
        db.commit()
    return None, token


def automatic_day_cap() -> int:
    return max(0, settings.search_day_credit_limit - settings.search_manual_reserved_credits)


def search_budget_state(db, user_id: str | None = None) -> dict:
    today = now_utc().astimezone(ZoneInfo("Asia/Shanghai"))
    day = today.strftime("%Y-%m-%d")

    def left(scope, cap):
        row = db.get(SearchBudget, scope)
        return max(0, cap - (row.credits if row else 0))

    daily = left("day:" + day, settings.search_day_credit_limit)
    monthly = left("month:" + today.strftime("%Y-%m"), settings.search_month_credit_limit)
    automatic = min(daily, monthly, left("auto_day:" + day, automatic_day_cap()))
    manual = min(daily, monthly)
    if user_id:
        manual = min(manual, left("user:" + user_id + ":" + day, settings.search_user_day_limit))
    return {
        "budget_exhausted": daily == 0 or monthly == 0,
        "limit_reason": "month" if monthly == 0 else "day" if daily == 0 else None,
        "automatic_remaining": automatic,
        "automatic_paused": automatic == 0 and daily > 0 and monthly > 0,
        "manual_remaining": manual,
    }


def search_cache_key(target: dict, focus: str) -> str:
    query, domains = request_spec(target, focus)
    return hashlib.sha256(
        json.dumps(
            ["gold-macro-v1" if target["kind"] == "gold" else SEARCH_POLICY_VERSION,
             provider().cache_namespace, target["watch_id"], focus, query, domains,
             target.get("time_range", "month")]
        ).encode()
    ).hexdigest()


async def discover(target: dict, focus: str = "recent", user_id: str | None = None) -> dict:
    if not configured():
        return {"status": "not_configured", "results": [], "search_credits": 0}
    if focus not in FOCUSES:
        return {"status": "unsupported_focus", "results": [], "search_credits": 0}
    requested_focus = focus
    if focus == "auto":
        plan = discovery_plan(target["kind"], target.get("preference", {}))
        target = {**target, "search_domains": plan["search_domains"]}
        focus = plan["effective_focus"]
    query, domains = request_spec(target, focus)
    adapter = provider()
    key = search_cache_key(target, focus)
    cached, token = claim(key, user_id)
    if cached is not None:
        return {
            **cached, "requested_focus": requested_focus, "effective_focus": focus,
            "time_range": target.get("time_range", "month"), "search_domains": domains,
        }
    # Reservations count attempted requests, including uncertain failures; no automatic retries.
    with SessionLocal() as db:
        run = AgentRun(user_id=user_id, kind=KIND, status="running", detail="")
        db.add(run)
        db.commit()
        run_id = run.id
    result = {"status": "failure", "results": [], "search_credits": 1, "cache_hit": False,
              "effective_focus": focus, "time_range": target.get("time_range", "month"), "search_domains": domains,
              "category": target["kind"]}
    try:
        # Sports news uses the provider's article-oriented index; stock PDFs retain general search.
        topic = "news" if target["kind"] in {"team", "gold"} else "general"
        rows = (await asyncio.wait_for(
            adapter.search(query, domains, topic=topic, time_range=target.get("time_range", "month")), timeout=15,
        ))[:12]
        enriched = 0
        if target["kind"] in {"stock", "index", "gold"}:
            # Search snippets can omit the named entity or publication date.
            # Read at most three approved publisher pages, without redirects.
            candidates = []
            for position, row in enumerate(rows):
                _, reason = normalize_result(row, target, domains, now_utc())
                if reason not in {None, "entity_mismatch", "missing_date"} or not isinstance(row, dict):
                    continue
                try:
                    url = eastmoney_url(row.get("url", ""))
                except (ValueError, TypeError):
                    continue
                candidates.append((position, url))
            for position, url in candidates[:3]:
                def read_public_page(url=url):
                    with httpx.Client(timeout=3, follow_redirects=False, trust_env=False) as client:
                        return read_eastmoney(client, url)
                try:
                    rows[position] = await asyncio.wait_for(asyncio.to_thread(read_public_page), timeout=4)
                    enriched += 1
                except Exception:
                    # Preserve diagnostics from the original search result on read failure.
                    continue
        dropped, ids, created, rejected = {}, [], 0, []
        with SessionLocal() as db:
            for row in rows:
                values, reason = normalize_result(row, target, domains, now_utc())
                if reason:
                    dropped[reason] = dropped.get(reason, 0) + 1
                    rejected.append(rejection_detail(row, reason, domains))
                    continue
                if focus in FOCUSES - {"auto", "recent"} and (
                    not kind_matches(content_kind(SimpleNamespace(**values)), focus)
                ):
                    dropped["focus_mismatch"] = dropped.get("focus_mismatch", 0) + 1
                    rejected.append(rejection_detail(row, "focus_mismatch", domains))
                    continue
                created += int(store_item(db, **values))
                item = db.scalar(
                    select(Item).where(
                        Item.canonical_url == values["canonical_url"], Item.watch_id == target["watch_id"]
                    )
                )
                if item:
                    ids.append(item.id)
                else:
                    dropped["url_owned_by_other_entity"] = dropped.get("url_owned_by_other_entity", 0) + 1
                    rejected.append(rejection_detail(row, "url_owned_by_other_entity", domains))
            db.commit()
        result.update(
            status="success",
            results=list(dict.fromkeys(ids)),
            entries=len(rows),
            matched=len(set(ids)),
            created=created,
            dropped=dropped,
            rejected=rejected,
            search_topic=topic,
            metadata_enriched=enriched,
        )
    except asyncio.CancelledError:
        result["error_type"] = "cancelled"
        raise
    except Exception as exc:
        # Never persist provider response bodies, API keys or request headers.
        result["error_type"] = type(exc).__name__
    finally:
        with SessionLocal() as db:
            now = now_utc()
            result["completed_at"] = now.isoformat()
            db.execute(
                update(SearchCache)
                .where(SearchCache.key == key, SearchCache.lease_token == token)
                .values(
                    payload=json.dumps(result),
                    expires_at=now + timedelta(hours=settings.search_cache_hours)
                    if result["status"] == "success" and result["results"]
                    else now + timedelta(minutes=5 if result["status"] != "success" else 15),
                    lease_until=now,
                )
            )
            run = db.get(AgentRun, run_id)
            run.status = result["status"]
            run.item_count = len(result["results"])
            run.finished_at = now
            run.detail = json.dumps({k: v for k, v in result.items() if k != "results"})
            db.commit()
    return {**result, "requested_focus": requested_focus}


def sync() -> dict:
    if not configured():
        return {"status": "not_configured", "search_credits": 0}
    with SessionLocal() as db:
        unique = {search_cache_key({**value, "time_range": "day"}, "recent"): (value, "recent")
                  for value in targets(db).values()}
        # Both direct gold reporting and US macro releases are baseline supply.
        # Share the plan across subscribers and retain all existing credit caps.
        for value in targets(db).values():
            if value["kind"] == "gold":
                unique[search_cache_key({**value, "time_range": "day"}, "macro")] = (value, "macro")
        # Personalized public entity/type plans share cache, never account metadata.
        for user_id in sorted(set(db.scalars(select(Watch.user_id)))):
            profile = acquisition_profile(db, user_id)
            for watch_id, value in targets(db, user_id).items():
                plan = discovery_plan(value["kind"], profile.get(watch_id, {}))
                focus = plan["effective_focus"]
                if focus != "recent" or plan["avoided_sources"]:
                    value = {**value, "search_domains": plan["search_domains"]}
                    key = search_cache_key({**value, "time_range": "day"}, focus)
                    unique[key] = (value, focus)
        budget = search_budget_state(db)
        remaining = budget["automatic_remaining"]
    with SessionLocal() as db:
        cache_by_key = {row.key: row for row in db.scalars(select(SearchCache))}
    now = now_utc()
    # Never spend the limited first ten slots on still-fresh cache hits. Oldest
    # searches come first so subscriptions after position ten can make progress.
    due, cadence_deferred = [], 0
    for value, focus in unique.values():
        value = {**value, "time_range": "day"}
        cache = cache_by_key.get(search_cache_key(value, focus))
        if cache and (_aware(cache.expires_at) > now or _aware(cache.lease_until) > now):
            continue
        try:
            payload = json.loads(cache.payload) if cache else {}
        except (ValueError, TypeError):
            payload = {}
        next_due = automatic_due_at(payload if isinstance(payload, dict) else {}, settings.search_auto_interval_hours)
        if next_due and next_due > now:
            cadence_deferred += 1
            continue
        due.append((value, focus, _aware(cache.expires_at) if cache else datetime.min.replace(tzinfo=UTC)))
    ordered = fair_order(due)
    results, category_results, dropped = [], {}, {}
    for target, focus, _ in ordered[: min(remaining, 10)]:
        results.append(asyncio.run(discover(target, focus)))
        result = results[-1]
        # Aggregate by public category, never expose individual subscriptions,
        # custom labels, questions or feedback in scheduler status.
        metrics = category_results.setdefault(target["kind"], {
            "attempts": 0, "successes": 0, "failures": 0,
            "entries": 0, "matched": 0, "created": 0, "search_credits": 0, "dropped": {},
        })
        metrics["attempts"] += 1
        metrics["successes"] += int(result["status"] == "success")
        metrics["failures"] += int(result["status"] == "failure")
        for field in ("entries", "matched", "created", "search_credits"):
            metrics[field] += result.get(field, 0)
        for reason, count in result.get("dropped", {}).items():
            metrics["dropped"][reason] = metrics["dropped"].get(reason, 0) + count
            dropped[reason] = dropped.get(reason, 0) + count
        if results[-1]["status"] == "budget_exhausted":
            break
    with SessionLocal() as db:
        budget = search_budget_state(db)
    return {
        "status": "partial" if any(r["status"] == "failure" for r in results) else "completed",
        "targets": len(results), "due_targets": len(due),
        "planned_targets": len(unique),
        "personalized_targets": sum(focus != "recent" or "search_domains" in value
                                    for value, focus in unique.values()),
        "deferred_targets": max(0, len(due) - len(results)),
        "search_credits": sum(r["search_credits"] for r in results),
        "entries": sum(r.get("entries", 0) for r in results),
        "matched": sum(r.get("matched", 0) for r in results),
        "created": sum(r.get("created", 0) for r in results),
        "budget_exhausted": budget["budget_exhausted"],
        "automatic_paused": budget["automatic_paused"],
        "automatic_remaining": budget["automatic_remaining"],
        "manual_remaining": budget["manual_remaining"],
        "cadence_deferred": cadence_deferred,
        "automatic_interval_hours": settings.search_auto_interval_hours,
        "category_results": category_results,
        "dropped": dropped,
        "time_range": "day",
    }


if __name__ == "__main__":
    print(sync())
