"""User-owned feedback steers bounded discovery, never grants a wider scope."""

import json

from sqlalchemy import select

from information_agent.discovery_policy import discovery_plan, entity_kind, publisher_domain
from information_agent.discovery_policy import preferred_focus as preferred_focus
from information_agent.models import Feedback, Item
from information_agent.personalization import matches, user_scope
from information_agent.preferences import KIND_LABELS, content_kind


def acquisition_profile(db, user_id: str) -> dict:
    enabled, topics = user_scope(db, user_id)
    events = list(db.scalars(select(Feedback).where(
        Feedback.user_id == user_id, Feedback.undone_at.is_(None),
    ).order_by(Feedback.created_at.desc(), Feedback.id.desc()).limit(500)))
    metadata = {item.id: item for item in db.scalars(select(Item).where(
        Item.id.in_({event.item_id for event in events}),
    ))}
    kinds = {key: entity_kind(key) for key in enabled}
    for topic in topics:
        kinds[topic.id] = next((kind for marker in json.loads(topic.keywords)
                               if (kind := entity_kind(marker))), None)
    result = {key: {"weights": {}, "source_weights": {}, "feedback_count": 0} for key in enabled}
    for event in reversed(events):
        item = metadata.get(event.item_id)
        if item is None or event.action not in {"interested", "not_interested"}:
            continue
        for watch_id in matches(item, enabled, topics):
            entry = result[watch_id]
            entry["feedback_count"] += 1
            if event.reason == "source":
                domain = publisher_domain(item.canonical_url, kinds[watch_id])
                if domain:
                    weights = entry["source_weights"]
                    weights[domain] = max(-3, min(3, weights.get(domain, 0) + (
                        1 if event.action == "interested" else -1
                    )))
                continue
            if event.reason != "content_type":
                continue
            kind = content_kind(item)
            weights = entry["weights"]
            weights[kind] = max(-3, min(3, weights.get(kind, 0) + (
                1 if event.action == "interested" else -1
            )))
    for watch_id, entry in result.items():
        entry["signals"] = [{"kind": kind, "label": KIND_LABELS[kind], "weight": weight}
                            for kind, weight in sorted(entry["weights"].items()) if weight]
        entry["source_signals"] = [{"domain": domain, "weight": weight}
                                   for domain, weight in sorted(entry["source_weights"].items()) if weight]
        entry.update(discovery_plan(kinds[watch_id], entry))
    return result
