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
    import httpx

    captured = []

    def capture_completion(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": []})

    original_base = settings.model_base_url
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(capture_completion)) as client:
            settings.model_base_url = "https://api.deepseek.com/v1"
            await model_agent.completion(client, [{"role": "system", "content": "Return JSON."}], [], True)
            await model_agent.completion(client, [], [], False)
            settings.model_base_url = "https://example.invalid/v1"
            await model_agent.completion(client, [], [], True)
        rows.append({"case": "official_deepseek_final_json_mode_only", "passed":
            captured[0].get("response_format") == {"type": "json_object"}
            and "response_format" not in captured[1] and "response_format" not in captured[2]})
    finally:
        settings.model_base_url = original_base

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
    await scenario("repeat_search_recovers_scoped_evidence", [search, search, final])
    recovery_trace = {}
    recovery_queue = iter([search, search, final])

    async def repeat_complete(*args):
        return next(recovery_queue)

    await model_agent.run("synthetic query", uid, [], recovery_trace, repeat_complete)
    recovery_tools = recovery_trace["tools"]
    rows.append({"case": "server_recovery_is_bounded_and_observable", "passed":
        len(recovery_tools) == 2
        and recovery_tools[1].get("actor") == "server_recovery"
        and recovery_tools[1]["arguments"] == {"item_id": item_id}
        and recovery_trace["skipped_tools"][0]["recovery_count"] == 1})
    await scenario(
        "found_candidates_cannot_claim_no_evidence",
        [search, response(answer={"answer": "none"})],
        "evidence_not_fetched",
    )
    parallel_search = [
        tool("search_items", {"limit": 1}),
        {**tool("search_items", {"limit": 1}), "id": "second-search"},
    ]
    await scenario("same_batch_repeat_search_preserves_evidence_budget", [response(parallel_search), evidence, final])
    captured_definitions = []
    sequence = iter([search, evidence, final])

    async def capture_complete(client, messages, definitions, final_round):
        captured_definitions.append([d["function"]["name"] for d in definitions])
        return next(sequence)

    await model_agent.run("synthetic query", uid, [], {}, capture_complete)
    rows.append(
        {"case": "evidence_stage_exposes_only_evidence_tool", "passed": captured_definitions[1] == ["get_evidence"]}
    )
    from datetime import UTC, datetime
    from unittest.mock import patch

    window_cases = [
        (
            "rolling_window_beijing_context_keeps_start_day_and_time",
            (datetime(2026, 9, 10, 14, 52, 40, tzinfo=UTC), datetime(2026, 10, 10, 14, 52, 40, tzinfo=UTC)),
            {"since": "2026-09-10T22:52:40+08:00", "until": "2026-10-10T22:52:40+08:00"},
        ),
        (
            "window_beijing_context_crosses_utc_midnight",
            (datetime(2026, 10, 8, 16, tzinfo=UTC), datetime(2026, 10, 9, 16, tzinfo=UTC)),
            {"since": "2026-10-09T00:00:00+08:00", "until": "2026-10-10T00:00:00+08:00"},
        ),
        ("unspecified_window_context_keeps_null_bounds", (None, None), {"since": None, "until": None}),
    ]
    for case_name, bounds, expected_window in window_cases:
        contexts = []

        async def window_complete(client, messages, definitions, final_round):
            contexts.append(json.loads(messages[1]["content"]))
            return response(answer={"answer": "No evidence", "evidence_ids": []})

        window_trace = {}
        with patch.object(model_agent, "query_window", return_value=bounds):
            await model_agent.run("synthetic window query", other_uid, [], window_trace, window_complete)
        rows.append({"case": case_name, "passed":
            contexts[0]["time_window_beijing"] == expected_window
            and window_trace["time_window_beijing"] == expected_window
            and contexts[0]["time_window"] == {
                "since": bounds[0].isoformat() if bounds[0] else None,
                "until": bounds[1].isoformat() if bounds[1] else None,
            }})
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
    with SessionLocal() as db:
        match_item = Item(
            watch_id="esports:cs2",
            canonical_url="https://example.invalid/synthetic-match",
            title="Synthetic Team 2 : 1 Opponent · 赛果",
            source_name="PandaScore · CS2 赛事数据",
            source_type="other", ingestion_mode="api", event_key="match", published_at=now_utc(),
        )
        db.add(match_item)
        db.commit()
        match_id = match_item.id
    for required, requested in (("news", "matches"), ("matches", "news"), ("all", "news")):
        selected = await SearchItems(uid, query_view=required).execute(limit=5, view=requested)
        ids = {r["id"] for r in selected}
        passed = (
            match_id not in ids and interview_id in ids if required == "news"
            else ids == {match_id} if required == "matches"
            else {match_id, interview_id}.issubset(ids)
        )
        rows.append({"case": "server_query_view_" + required, "passed": passed})
    from information_agent.agent_tools import beijing_timestamp, news_age_label

    rows.append({"case": "evidence_dates_use_beijing", "passed":
        news_age_label("2026-09-27T16:00:00+00:00") == "2026-09-28"
        and news_age_label(None) == "发布时间未知"})
    rows.append({"case": "tools_include_explicit_beijing_timestamp", "passed":
        beijing_timestamp("2026-09-27T16:00:00+00:00") == "2026-09-28T00:00:00+08:00"
        and beijing_timestamp(None) is None
        and (await SearchItems(uid).execute(limit=1))[0]["published_at_beijing"].endswith("+08:00")
        and (await GetEvidence(uid).execute(item_id))["published_at_beijing"].endswith("+08:00")})
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
    from information_agent.news_quality import news_exclusion

    generic_title = "证券时报电子报实时通过手机APP、网站免费阅读重大财经新闻资讯及上市公司公告"
    rows.append(
        {
            "case": "generic_stock_page_title_excluded",
            "passed": news_exclusion(generic_title, "stock:002491", "epaper.stcn.com · 股票资讯")
            == "generic_page_title"
            and news_exclusion("通鼎互联中标采购项目", "stock:002491", "epaper.stcn.com · 股票资讯") is None,
        }
    )
    from information_agent.agent_tools import SearchItems

    with SessionLocal() as db:
        comparison_user = User(email="synthetic-comparison@example.invalid", password_hash="synthetic")
        db.add(comparison_user)
        db.flush()
        db.add_all([
            Watch(user_id=comparison_user.id, watch_id="esports:cs2"),
            Watch(user_id=comparison_user.id, watch_id="gold:london"),
        ])
        db.commit()
        comparison_uid = comparison_user.id
    comparison_items = await SearchItems(
        comparison_uid, query_watch_ids=["esports:cs2", "gold:london"]
    ).execute(limit=5, watch_id="esports:cs2")
    isolated_items = await SearchItems(
        uid, query_watch_ids=["esports:cs2", "gold:london"]
    ).execute(limit=5, watch_id="gold:london")
    rows.append({"case": "server_query_objects_override_partial_model_selection", "passed":
        {item_id, foreign_id}.issubset({item["id"] for item in comparison_items})
        and len(comparison_items) <= 5})
    rows.append({"case": "server_query_objects_keep_user_isolation", "passed":
        item_id in {item["id"] for item in isolated_items}
        and foreign_id not in {item["id"] for item in isolated_items}
        and all(item["watch_id"] == "esports:cs2" for item in isolated_items)})
    mixed = await SearchItems(uid, query_view="all").execute(limit=2, view="news")
    rows.append({"case": "mixed_query_budget_preserves_news_and_matches", "passed":
        len(mixed) == 2 and {item["content_kind"] == "match" for item in mixed} == {True, False}})
    comparison_small = await SearchItems(
        comparison_uid, query_watch_ids=["esports:cs2", "gold:london"]
    ).execute(limit=2, watch_id="esports:cs2")
    rows.append({"case": "multi_object_budget_preserves_each_object", "passed":
        len(comparison_small) == 2
        and {item["watch_id"] for item in comparison_small} == {"esports:cs2", "gold:london"}})
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from information_agent.acquisition_preferences import acquisition_profile, preferred_focus
    from information_agent.api import router
    from information_agent.models import Topic
    from information_agent.security import issue_token
    from information_agent.web_search import STOCK_DOMAINS, normalize_result, targets

    app = FastAPI()
    app.include_router(router)
    api_client = TestClient(app)
    headers_a = {"Authorization": "Bearer " + issue_token(uid)}
    headers_b = {"Authorization": "Bearer " + issue_token(other_uid)}
    index_response = api_client.post("/api/topics", headers=headers_a, json={
        "stock_code": "000001", "asset_type": "index",
    })
    index_topic = index_response.json()
    rows.append({"case": "index_subscription_has_distinct_canonical_identity", "passed":
        index_response.status_code == 201 and index_topic["keywords"] == ["index:sh:000001"]})
    foreign_update = api_client.put("/api/watches", headers=headers_b, json={
        "watch_id": index_topic["id"], "enabled": True,
    })
    desk_a = api_client.get("/api/desk", headers=headers_a).json()
    desk_b = api_client.get("/api/desk", headers=headers_b).json()
    rows.append({"case": "desk_and_watch_options_keep_custom_accounts_isolated", "passed":
        foreign_update.status_code == 422
        and index_topic["id"] in desk_a["watches"]["watch_ids"]
        and index_topic["id"] not in desk_b["watches"]["watch_ids"]
        and not desk_b["topics"]["topics"]
        and all(entry["id"] in desk_b["watches"]["watch_ids"] for entry in desk_b["catalog"]["watches"])})
    rows.append({"case": "desk_requires_authentication", "passed":
        api_client.get("/api/desk").status_code == 401
        and api_client.get("/api/preferences").status_code == 401})
    index_target = {"watch_id": "index:sh:000001", "name": "上证指数", "kind": "index"}
    bank_target = {"watch_id": "stock:000001", "name": "平安银行", "kind": "stock"}
    article_row = {"title": "上证指数ETF资金流入", "content": "上证综合指数(000001)消息",
                   "url": "https://finance.eastmoney.com/a/202610083889579373.html"}
    frozen_now = datetime(2026, 10, 11, 0, tzinfo=UTC)
    indexed, index_reason = normalize_result(article_row, index_target, STOCK_DOMAINS, frozen_now)
    banked, bank_reason = normalize_result(article_row, bank_target, STOCK_DOMAINS, frozen_now)
    rows.append({"case": "eastmoney_url_date_recovers_index_but_rejects_same_code_bank", "passed":
        index_reason is None and indexed["watch_id"] == "index:sh:000001"
        and indexed["published_at"].isoformat() == "2026-10-07T16:00:00+00:00"
        and banked is None and bank_reason == "entity_mismatch"})
    with SessionLocal() as db:
        pref_topic = Topic(user_id=uid, name="Synthetic private team label", keywords='["team:cs2:team-spirit"]')
        db.add(pref_topic)
        db.flush()
        db.add(Watch(user_id=uid, watch_id=pref_topic.id))
        interview = Item(watch_id="team:cs2:team-spirit", title="donk interview", source_name="Synthetic 战队新闻",
                         source_type="media", ingestion_mode="manual", event_key="preference-fixture",
                         canonical_url="https://example.invalid/preference-interview", published_at=now_utc())
        db.add(interview)
        db.flush()
        interest = Feedback(user_id=uid, item_id=interview.id, action="interested", reason="content_type")
        db.add(interest)
        db.commit()
        profile_a, profile_b = acquisition_profile(db, uid), acquisition_profile(db, other_uid)
        rows.append({"case": "positive_feedback_steers_only_owner_acquisition", "passed":
            preferred_focus("team", profile_a[pref_topic.id]) == "interview"
            and pref_topic.id not in profile_b
            and targets(db, uid)[pref_topic.id]["name"] == "Team Spirit"})
        interest.undone_at = now_utc()
        db.commit()
        rows.append({"case": "feedback_undo_restores_broad_acquisition", "passed":
            preferred_focus("team", acquisition_profile(db, uid)[pref_topic.id]) == "recent"})
        db.add(Feedback(user_id=uid, item_id=interview.id, action="not_interested", reason="content_type"))
        db.commit()
        rows.append({"case": "negative_interview_feedback_explores_roster_without_erasing_library", "passed":
            preferred_focus("team", acquisition_profile(db, uid)[pref_topic.id]) == "roster"
            and db.get(Item, interview.id) is not None})
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
