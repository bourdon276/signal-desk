"""Bounded downloads and idempotent inserts shared by fixed-source adapters."""

import hashlib
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from information_agent.models import Item

MAX_BYTES = 2_000_000


def download(client: httpx.Client, url: str, method: str = "GET", **kwargs) -> bytes:
    content = bytearray()
    headers = {"User-Agent": "SignalDesk/0.2 news reader"}
    headers.update(kwargs.pop("headers", {}))
    with client.stream(method, url, headers=headers, **kwargs) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            if len(content) + len(chunk) > MAX_BYTES:
                raise ValueError("source response exceeds size limit")
            content.extend(chunk)
    return bytes(content)


def safe_link(value: str, hosts: set[str]) -> str | None:
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or parts.hostname not in hosts
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
        ):
            return None
        return urlunsplit(("https", parts.hostname, parts.path, parts.query, ""))
    except ValueError:
        return None


def store_item(db, **values) -> bool:
    url = values["canonical_url"]
    existing = db.scalar(select(Item).where(Item.canonical_url == url))
    if existing is not None:
        # Repair legacy 000001 code collisions only after an approved publisher
        # result has independently matched the distinct SH index identity.
        host = urlsplit(url).hostname
        repair_index = (
            existing.watch_id == "stock:000001"
            and values["watch_id"] == "index:sh:000001"
            and host in {"finance.eastmoney.com", "stock.eastmoney.com"}
            and "上证" in values["title"] and "平安银行" not in values["title"]
        )
        refresh_publisher_excerpt = (
            existing.watch_id == values["watch_id"] and values.get("ingestion_mode") == "manual"
            and host in {"finance.eastmoney.com", "stock.eastmoney.com"}
        )
        if repair_index or refresh_publisher_excerpt:
            existing.watch_id = values["watch_id"]
            for key in ("title", "summary", "source_name", "source_type", "ingestion_mode", "published_at"):
                setattr(existing, key, values[key])
            db.flush()
        return False
    values["event_key"] = hashlib.sha256(url.encode()).hexdigest()[:32]
    try:
        with db.begin_nested():
            db.add(Item(**values))
            db.flush()
    except IntegrityError:
        # Another worker may have inserted the same URL after the lookup.
        return False
    return True
