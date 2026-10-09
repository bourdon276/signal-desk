"""Offline, synthetic regression eval. Not a real-model quality benchmark."""

import asyncio
import json
import os
import tempfile
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory(prefix="signal-agent-eval-") as directory:
        os.environ["DATABASE_URL"] = "sqlite:///" + directory + "/eval.db"
        os.environ["MODEL_ENABLED"] = "false"
        os.environ["SYNC_IN_WEB"] = "false"
        asyncio.run(evaluate())


async def evaluate():
    from information_agent import model_agent
    from information_agent.agent_tools import GetEvidence
    from information_agent.config import settings
    from information_agent.db import Base, SessionLocal, engine
    from information_agent.models import Feedback, Item, ModelBudget, User, Watch, now_utc
    from information_agent.ranking import ranked_items

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        user = User(email="synthetic-a@example.invalid", password_hash="synthetic")
        other = User(email="synthetic-b@example.invalid", password_hash="synthetic")
        db.add_all([user, other])
        db.flush()
        db.add_all([Watch(user_id=user.id, watch_id="esports:cs2"), Watch(user_id=other.id, watch_id="gold:london")])
        own = Item(
            watch_id="esports:cs2",
            canonical_url="https://example.invalid/synthetic-cs2",
            title="Synthetic CS2 fixture",
            summary="Synthetic regression evidence only.",
            source_name="Synthetic",
            source_type="other",
            ingestion_mode="manual",
            event_key="a",
            published_at=now_utc(),
        )
        foreign = Item(
            watch_id="gold:london",
            canonical_url="https://example.invalid/synthetic-gold",
            title="Synthetic gold",
            source_name="Synthetic",
            source_type="other",
            ingestion_mode="manual",
            event_key="b",
            published_at=now_utc(),
        )
        db.add_all([own, foreign])
        db.commit()
        uid, other_uid, item_id, foreign_id = user.id, other.id, own.id, foreign.id

    def tool(name, args):
        return {"id": "call-" + name, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}

    def response(calls=None, answer=None):
        return {
            "choices": [{"message": {"tool_calls": calls, "content": json.dumps(answer) if answer else None}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }

    search = response([tool("search_items", {"limit": 1})])
    evidence = response([tool("get_evidence", {"item_id": item_id})])
    final = response(answer={"answer": "Synthetic fact [" + item_id + "]", "evidence_ids": [item_id]})
    rows = []

    async def scenario(name, responses, expected=None, empty_user=False):
        queue = iter(responses)

        async def complete(*args):
            value = next(queue)
            if isinstance(value, Exception):
                raise value
            return value

        trace = {}
        try:
            result = await model_agent.run("synthetic query", other_uid if empty_user else uid, [], trace, complete)
            passed = expected is None and result["mode"] == ("model_no_evidence" if empty_user else "model_agent")
            error = None
        except Exception as exc:
            error = str(exc)
            passed = expected is not None and error == expected
        rows.append(
            {
                "case": name,
                "passed": passed,
                "error": error,
                "model_calls": trace.get("model_calls"),
                "tool_calls": len(trace.get("tools", [])),
            }
        )

    await scenario("grounded_three_rounds", [search, evidence, final])
    await scenario("repeat_search_without_evidence_denied", [search, search, final], "evidence_required")
    await scenario(
        "found_candidates_cannot_claim_no_evidence",
        [search, response(answer={"answer": "none"})],
        "evidence_not_fetched",
    )
    captured_definitions = []
    sequence = iter([search, evidence, final])

    async def capture_complete(client, messages, definitions, final_round):
        captured_definitions.append([d["function"]["name"] for d in definitions])
        return next(sequence)

    await model_agent.run("synthetic query", uid, [], {}, capture_complete)
    rows.append(
        {"case": "evidence_stage_exposes_only_evidence_tool", "passed": captured_definitions[1] == ["get_evidence"]}
    )
    await scenario(
        "no_evidence_cannot_invent_answer",
        [response(answer={"answer": "invented", "evidence_ids": []})],
        empty_user=True,
    )
    await scenario("unknown_tool_denied", [response([tool("exec_shell", {"command": "echo x"})])], "invalid_tool")
    await scenario(
        "extra_identity_parameter_denied",
        [response([tool("search_items", {"limit": 1, "user_id": other_uid})])],
        "tool_error",
    )
    await scenario("oversized_search_denied", [response([tool("search_items", {"limit": 100})])], "tool_error")
    await scenario(
        "foreign_unsearched_evidence_denied",
        [search, response([tool("get_evidence", {"item_id": foreign_id})])],
        "unsearched_evidence",
    )
    await scenario(
        "forged_citation_denied",
        [search, evidence, response(answer={"answer": "fake", "evidence_ids": [foreign_id]})],
        "invalid_citation",
    )
    await scenario(
        "invented_url_denied",
        [
            search,
            evidence,
            response(answer={"answer": "https://evil.invalid [" + item_id + "]", "evidence_ids": [item_id]}),
        ],
        "invalid_citation",
    )
    await scenario(
        "missing_inline_citation_denied",
        [search, evidence, response(answer={"answer": "unsupported", "evidence_ids": [item_id]})],
        "missing_inline_citation",
    )
    await scenario("seventh_tool_denied", [response([tool("search_items", {"limit": 1})] * 7)], "tool_limit")
    await scenario("third_round_cannot_call_tools", [search, evidence, search], "tool_limit")
    await scenario(
        "provider_error_propagates_for_fallback", [RuntimeError("provider_unavailable")], "provider_unavailable"
    )
    rows.append({"case": "direct_tool_user_isolation", "passed": await GetEvidence(uid).execute(foreign_id) is None})
    with SessionLocal() as db:
        event = Feedback(user_id=uid, item_id=item_id, action="not_interested")
        db.add(event)
        db.commit()
        hidden = not ranked_items(db, uid)
        other_unchanged = len(ranked_items(db, other_uid)) == 1
        event.undone_at = now_utc()
        db.commit()
        rows.append(
            {
                "case": "feedback_hidden_isolated_and_undo",
                "passed": hidden and other_unchanged and bool(ranked_items(db, uid)),
            }
        )
    settings.model_input_cny_per_million = 2
    settings.model_output_cny_per_million = 8
    from unittest.mock import AsyncMock, patch

    from information_agent.api import AskInput, ask, my_run
    from information_agent.models import AgentRun

    with SessionLocal() as db:
        logged_user = db.get(User, uid)
        with (
            patch.object(model_agent, "configured", return_value=True),
            patch.object(model_agent, "run", new=AsyncMock(side_effect=RuntimeError("scripted_provider_failure"))),
        ):
            fallback = await ask(AskInput(question="我关注的消息", use_model=True), logged_user, db)
        failed_run = db.get(AgentRun, fallback["model_run_id"])
        rows.append(
            {
                "case": "api_provider_failure_returns_evidence_fallback",
                "passed": fallback["mode"] == "model_fallback" and failed_run.status == "failure",
            }
        )
        try:
            my_run(failed_run.id, db.get(User, other_uid), db)
            denied = False
        except Exception as exc:
            denied = getattr(exc, "status_code", None) == 404
        rows.append({"case": "run_trace_user_isolation", "passed": denied})
    # Clear only this temporary synthetic DB's budget rows before the independent budget case.
    with SessionLocal() as db:
        from sqlalchemy import delete

        db.execute(delete(ModelBudget))
        db.commit()
    settings.model_day_budget_cny = 0.12
    first = model_agent.reserve(uid)
    try:
        model_agent.reserve(uid)
        blocked = False
    except RuntimeError as exc:
        blocked = str(exc) == "budget_exhausted"
    with SessionLocal() as db:
        count = db.get(ModelBudget, first[0][0]).requests
    rows.append({"case": "budget_reservation_atomic_rollback", "passed": blocked and count == 1})
    model_agent.settle(*first, 1000)
    with SessionLocal() as db:
        charged = db.get(ModelBudget, first[0][0]).charged_micro_cny
    rows.append({"case": "budget_settlement", "passed": charged == 1000})
    from information_agent.agent_tools import SearchItems
    from information_agent.query_policy import query_filters

    rows.append(
        {
            "case": "negated_matches_do_not_select_matches",
            "passed": query_filters("总结绿龙近7天的采访，只使用采访，不要比赛")
            == {"view": "news", "news_kind": "interview"},
        }
    )
    rows.append(
        {
            "case": "combined_news_matches_remain_all",
            "passed": query_filters("总结绿龙新闻和比赛") == {"view": "all", "news_kind": "all"},
        }
    )
    with SessionLocal() as db:
        interview_item = Item(
            watch_id="esports:cs2",
            canonical_url="https://example.invalid/synthetic-interview",
            title="Synthetic interview",
            summary="Synthetic interview excerpt",
            source_name="完美世界电竞 · 战队采访",
            source_type="media",
            ingestion_mode="api",
            event_key="interview",
            published_at=now_utc(),
        )
        db.add(interview_item)
        db.commit()
        interview_id = interview_item.id
    selected = await SearchItems(uid, news_kind="interview").execute(limit=5, view="matches")
    rows.append(
        {
            "case": "server_interview_scope_overrides_wrong_view",
            "passed": [r["id"] for r in selected] == [interview_id] and selected[0]["content_kind"] == "interview",
        }
    )
    from datetime import timedelta
    from types import SimpleNamespace

    from information_agent.event_identity import event_identity, group_rows

    def news(url, title="A sufficiently long exact interview headline", watch_id="team:cs2:spirit", stamp=None):
        return SimpleNamespace(
            canonical_url=url,
            title=title,
            watch_id=watch_id,
            source_name="Synthetic · 战队新闻",
            published_at=stamp or now_utc(),
            event_key=url,
        )

    pw = news("https://news.wmpvp.com/news.html?gameTypeStr=2&id=304545", "不同中文标题")
    dust = news(
        "https://www.dust2.com.br/noticias/78712/donk-temos-a-confianca-de-que-ainda-podemos-vencer-a-pro-league",
        "Different Portuguese title",
    )
    unrelated = news("https://www.dust2.com.br/noticias/78713/another-interview", "Other interview")
    rows.append(
        {
            "case": "audited_cross_language_reprint_pair",
            "passed": event_identity(pw)[0] == event_identity(dust)[0]
            and event_identity(dust)[0] != event_identity(unrelated)[0],
        }
    )
    stamp = now_utc()
    a = news("https://example.invalid/a", stamp=stamp)
    b = news("https://example.invalid/b", stamp=stamp)
    c = news("https://example.invalid/c", stamp=stamp + timedelta(days=1))
    d = news("https://example.invalid/d", watch_id="team:cs2:other", stamp=stamp)
    rows.append(
        {
            "case": "exact_title_group_object_date_boundaries",
            "passed": event_identity(a)[0] == event_identity(b)[0]
            and event_identity(a)[0] != event_identity(c)[0]
            and event_identity(a)[0] != event_identity(d)[0],
        }
    )

    def row(key, read):
        return {
            "id": key,
            "event_key": "one-event",
            "is_read": read,
            "title": key,
            "url": "https://example.invalid/" + key,
            "source_name": "Synthetic",
            "published_at": stamp.isoformat(),
        }

    grouped = group_rows([row("read", True), row("unread", False)])
    rows.append(
        {
            "case": "event_group_preserves_unread_and_source_links",
            "passed": len(grouped) == 1
            and grouped[0]["id"] == "unread"
            and grouped[0]["source_count"] == 2
            and grouped[0]["related_sources"][0]["id"] == "read",
        }
    )
    with SessionLocal() as db:
        grouping_user = User(email="grouping@example.invalid", password_hash="synthetic")
        db.add(grouping_user)
        db.flush()
        db.add(Watch(user_id=grouping_user.id, watch_id="team:cs2:spirit"))
        for metadata in (pw, dust):
            db.add(
                Item(
                    watch_id="team:cs2:spirit",
                    canonical_url=metadata.canonical_url,
                    title=metadata.title,
                    source_name="完美世界电竞 · 战队采访",
                    source_type="media",
                    ingestion_mode="manual",
                    event_key=metadata.event_key,
                    published_at=stamp,
                )
            )
        db.commit()
        grouped_rows = ranked_items(db, grouping_user.id)
        raw_rows = ranked_items(db, grouping_user.id, group_events=False)
        rows.append(
            {
                "case": "feed_groups_but_tools_keep_two_records",
                "passed": len(grouped_rows) == 1 and grouped_rows[0]["source_count"] == 2 and len(raw_rows) == 2,
            }
        )
        db.add(Feedback(user_id=grouping_user.id, item_id=raw_rows[0]["id"], action="duplicate"))
        db.commit()
        rows.append(
            {
                "case": "duplicate_feedback_covers_verified_reprint_event",
                "passed": not ranked_items(db, grouping_user.id) and bool(ranked_items(db, uid)),
            }
        )
    report = {
        "kind": "offline_synthetic_scripted_regression",
        "real_model_calls": 0,
        "real_news_labels": 0,
        "passed": sum(r["passed"] for r in rows),
        "total": len(rows),
        "cases": rows,
        "limitations": [
            "Scripted model responses; does not measure model decision quality or factual grounding.",
            "Synthetic database, not real user or news data. No API key used.",
        ],
    }
    target = Path("data/eval/agent-regression.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
