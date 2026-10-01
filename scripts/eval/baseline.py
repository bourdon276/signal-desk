"""Deterministic keyword and recency baseline for authorized normalized items."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


ALIASES = {
    "stock:002491": ("通鼎互联", "002491"),
    "stock:002296": ("辉煌科技", "002296"),
    "gold:london": ("伦敦金", "现货黄金", "国际金价", "黄金市场", "金价"),
    "esports:lol": ("英雄联盟", "league of legends", "lol", "lpl"),
    "esports:cs2": ("cs2", "cs:go", "csgo", "counter-strike", "反恐精英"),
    "esports:valorant": ("无畏契约", "瓦罗兰特", "valorant", "vct"),
}


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc).timestamp()
    except ValueError as exc:
        raise ValueError(f"invalid published_at {value!r}: {exc}") from exc


def load_items(path: Path) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                for field in ("item_id", "title", "url"):
                    if not isinstance(item.get(field), str) or not item[field]:
                        raise ValueError(f"missing or invalid {field}")
                if item["item_id"] in seen:
                    raise ValueError(f"duplicate item_id {item['item_id']}")
                seen.add(item["item_id"])
                if not isinstance(item.get("summary", ""), str):
                    raise ValueError("invalid summary")
                item["_timestamp"] = timestamp(item.get("published_at"))
                items.append(item)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return items


def rank(items: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for watch_id, aliases in ALIASES.items():
        matches = []
        for item in items:
            haystack = normalize(item["title"] + " " + item.get("summary", ""))
            matched = [term for term in aliases if normalize(term) in haystack]
            if matched:
                matches.append((item, matched))
        matches.sort(
            key=lambda pair: (
                pair[0]["_timestamp"] is None,
                -(pair[0]["_timestamp"] or 0),
                pair[0]["item_id"],
            )
        )
        for position, (item, matched) in enumerate(matches, 1):
            rows.append(
                {
                    "watch_id": watch_id,
                    "rank": position,
                    "item_id": item["item_id"],
                    "published_at": item.get("published_at") or "",
                    "matched_terms": "|".join(matched),
                    "url": item["url"],
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows = rank(load_items(args.input))
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("watch_id", "rank", "item_id", "published_at", "matched_terms", "url"),
        )
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
