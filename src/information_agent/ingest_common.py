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
    with client.stream(method, url, headers={"User-Agent": "SignalDesk/0.2 news reader"}, **kwargs) as response:
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
    if db.scalar(select(Item.id).where(Item.canonical_url == url)) is not None:
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
