"""Canonical keys for entity subscriptions."""

import hashlib
import re
import unicodedata

_TEAM_ALIASES = {
    "绿龙": "Team Spirit",
    "greendragon": "Team Spirit",
    "teamspirit": "Team Spirit",
}


def normalize_entity_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in normalized if char.isalnum())


def canonical_team_name(value: str) -> str:
    cleaned = " ".join(unicodedata.normalize("NFKC", value).strip().split())
    alias = _TEAM_ALIASES.get(normalize_entity_name(cleaned))
    return alias or cleaned


def team_watch_id(value: str) -> str:
    canonical = canonical_team_name(value)
    slug = re.sub(r"[^a-z0-9]+", "-", canonical.casefold()).strip("-")
    if not slug:
        slug = hashlib.sha256(normalize_entity_name(canonical).encode()).hexdigest()[:16]
    return f"team:cs2:{slug}"[:64]


def is_team_watch_id(value: str) -> bool:
    return value.startswith("team:cs2:")
