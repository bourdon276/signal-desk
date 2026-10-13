"""Automatic discovery cadence and entity fairness, independent of manual cache TTL."""

from collections import deque
from datetime import UTC, datetime, timedelta


def automatic_due_at(payload: dict, interval_hours: int) -> datetime | None:
    value = payload.get("completed_at")
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    # A failed provider request gets a six-hour delay; an empty successful search
    # uses the normal interval, rather than burning a credit every hour.
    hours = interval_hours if payload.get("status") == "success" else 6
    return stamp + timedelta(hours=hours)


def fair_order(rows: list[tuple]) -> list[tuple]:
    """Each entity gets one turn before another direction of the same entity."""
    groups = {}
    for row in sorted(rows, key=lambda r: (r[2], r[0]["watch_id"], r[1] != "recent", r[1])):
        groups.setdefault(row[0]["watch_id"], deque()).append(row)
    result = []
    while groups:
        for marker in list(groups):
            result.append(groups[marker].popleft())
            if not groups[marker]:
                del groups[marker]
    return result
