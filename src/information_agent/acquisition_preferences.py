"""User-owned feedback steers bounded discovery, never grants a wider scope."""

from sqlalchemy import select

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
    result = {key: {"weights": {}, "feedback_count": 0} for key in enabled}
    for event in reversed(events):
        item = metadata.get(event.item_id)
        if item is None or event.action not in {"interested", "not_interested"}:
            continue
        for watch_id in matches(item, enabled, topics):
            entry = result[watch_id]
            entry["feedback_count"] += 1
            if event.reason != "content_type":
                continue
            kind = content_kind(item)
            weights = entry["weights"]
            weights[kind] = max(-3, min(3, weights.get(kind, 0) + (
                1 if event.action == "interested" else -1
            )))
    for entry in result.values():
        entry["signals"] = [{"kind": kind, "label": KIND_LABELS[kind], "weight": weight}
                            for kind, weight in sorted(entry["weights"].items()) if weight]
    return result


def preferred_focus(kind: str, profile: dict) -> str:
    allowed = ("interview", "roster") if kind == "team" else ("financial",) if kind == "stock" else ()
    weights = profile.get("weights", {})
    positive = [focus for focus in allowed if weights.get(focus, 0) > 0]
    if positive:
        return max(positive, key=lambda focus: weights[focus])
    if kind == "team" and any(weights.get(focus, 0) < 0 for focus in allowed):
        alternatives = [focus for focus in allowed if weights.get(focus, 0) >= 0]
        if alternatives:
            return alternatives[0]
    # Keep discovery broad when there is no explicit positive direction.
    # Negative feedback downranks results; it must not remove the remaining supply.
    return "recent"
