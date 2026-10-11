"""Shared access policy for feed, feedback and evidence tools."""

import json
import re

from sqlalchemy import or_, select

from information_agent.entities import is_team_watch_id
from information_agent.models import Item, Topic, Watch


def user_scope(db, user_id):
    enabled = set(db.scalars(select(Watch.watch_id).where(Watch.user_id == user_id)))
    topics = list(db.scalars(select(Topic).where(Topic.user_id == user_id, Topic.id.in_(enabled))))
    return enabled, topics


def matches(item, enabled, topics):
    result = [item.watch_id] if item.watch_id in enabled else []
    text = f"{item.title} {item.summary} {item.source_name} {item.watch_id}".casefold()
    for topic in topics:
        if any(
            item.watch_id == keyword
            if re.fullmatch(r"(?:stock:|index:(?:sh|sz):)[0-9]{6}", keyword) or is_team_watch_id(keyword)
            else keyword.casefold() in text
            for keyword in json.loads(topic.keywords)
        ):
            result.append(topic.id)
    return result


def candidate_filter(enabled, topics):
    clauses = [Item.watch_id.in_(enabled)]
    for topic in topics:
        for keyword in json.loads(topic.keywords):
            if re.fullmatch(r"(?:stock:|index:(?:sh|sz):)[0-9]{6}", keyword) or is_team_watch_id(keyword):
                clauses.append(Item.watch_id == keyword)
                continue
            pattern = "%" + keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            clauses.extend(
                column.ilike(pattern, escape="\\")
                for column in (Item.title, Item.summary, Item.source_name, Item.watch_id)
            )
    return or_(*clauses)


def overview(item):
    from information_agent.article_reader import clean_excerpt

    text = clean_excerpt(item.summary, item.title, item.watch_id)
    if text:
        return {"text": text, "kind": "正文摘要" if item.article_body else (
            "搜索摘录" if item.ingestion_mode == "search" else "来源摘录"
        )}
    return {"text": "点击标题，在阅讯读取正文。", "kind": "正文阅读"}


def article_url(item):
    """A provider record key is not evidence that a public article exists."""
    if item.source_name == "PandaScore · CS2 赛事数据":
        return None
    return item.canonical_url
