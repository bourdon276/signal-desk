"""Synthetic memory/reading isolation checks against real handlers, in a temporary database."""

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import patch


def main():
    with tempfile.TemporaryDirectory(prefix="signal-memory-eval-") as directory:
        os.environ["DATABASE_URL"] = "sqlite:///" + directory + "/eval.db"
        os.environ["SYNC_IN_WEB"] = "false"
        os.environ["SEARCH_ENABLED"] = "false"
        evaluate()


def evaluate():
    from fastapi import HTTPException
    from sqlalchemy import func, select

    from information_agent.acquisition_preferences import acquisition_profile
    from information_agent.api import FeedbackInput, add_feedback, undo_feedback
    from information_agent.db import Base, SessionLocal, engine
    from information_agent.models import AgentRun, Feedback, Item, Reading, Topic, User, Watch
    from information_agent.ranking import ranked_items
    from information_agent.sources import state
    from information_agent.supply_audit import daily_search_summary
    from information_agent.web_search import request_spec, targets

    Base.metadata.create_all(engine)
    now = datetime(2026, 10, 14, 9, tzinfo=UTC)
    results = []

    def check(name, condition):
        results.append({"case": name, "passed": bool(condition)})
        assert condition, name

    with SessionLocal() as db:
        a, b = User(email="a@example.invalid", password_hash="fixture"), User(
            email="b@example.invalid", password_hash="fixture",
        )
        db.add_all([a, b])
        db.flush()
        team = "team:cs2:team-spirit"
        for user, topic_id in ((a, "custom:a"), (b, "custom:b")):
            db.add(Topic(id=topic_id, user_id=user.id, name="Private fixture label",
                         keywords=json.dumps([team])))
            db.add_all([Watch(user_id=user.id, watch_id=topic_id), Watch(user_id=user.id, watch_id="stock:002491")])

        def item(key, marker, title, url, source):
            row = Item(watch_id=marker, title=title, canonical_url=url, source_name=source,
                       source_type="media", ingestion_mode="manual", event_key=key,
                       published_at=now - timedelta(hours=1), summary="Synthetic evaluation only.")
            db.add(row)
            return row

        interview = item("i1", team, 'donk: "Synthetic interview one"', "https://www.hltv.org/news/1/fixture", "HLTV")
        future = item("i2", team, 'sh1ro: "Synthetic interview two"', "https://www.hltv.org/news/2/fixture", "HLTV")
        roster = item("r1", team, "Synthetic roster joins fixture", "https://www.dust2.com.br/noticias/1/fixture",
                      "Dust2 Brasil · 战队新闻")
        other_roster = item("r2", team, "Synthetic other player departs fixture",
                            "https://www.dust2.com.br/noticias/2/fixture", "Dust2 Brasil · 战队新闻")
        stock1 = item("s1", "stock:002491", "通鼎互联合成财报一", "https://finance.eastmoney.com/a/202610140001.html",
                      "东方财富 · 股票资讯")
        stock2 = item("s2", "stock:002491", "通鼎互联合成财报二", "https://stock.eastmoney.com/a/202610140002.html",
                      "stock.eastmoney.com · 股票资讯")
        stock3 = item("s3", "stock:002491", "通鼎互联合成财报三", "https://www.stcn.com/article/detail/1.html",
                      "证券时报")
        foreign = item("f1", "stock:002296", "辉煌科技合成财报", "https://www.stcn.com/article/detail/2.html",
                       "证券时报")
        db.commit()
        a_id, b_id = a.id, b.id

        with patch("information_agent.ranking.datetime", wraps=datetime) as clock:
            clock.now.return_value = now

            def scores(uid):
                return {r["id"]: r["score"] for r in ranked_items(db, uid, group_events=False)}

            before_a, before_b = scores(a_id), scores(b_id)
            add_feedback(FeedbackInput(item_id=interview.id, action="interested", reason="content_type"), a, db)
            after = scores(a_id)
            check("positive_type_affects_unseen_same_type", after[future.id] > before_a[future.id])
            check("type_feedback_does_not_change_other_type_or_stock", after[roster.id] == before_a[roster.id]
                  and after[stock2.id] == before_a[stock2.id])
            check("feedback_does_not_change_other_user", scores(b_id) == before_b)
            profile = acquisition_profile(db, a_id)["custom:a"]
            check("positive_interview_steers_discovery", profile["effective_focus"] == "interview")
            target = targets(db, a_id)["custom:a"]
            query, _ = request_spec(target, profile["effective_focus"])
            check("discovery_uses_public_identity_not_private_label", "Private fixture label" not in query
                  and "Team Spirit" in query)

            hidden = add_feedback(FeedbackInput(item_id=roster.id, action="not_interested", reason="hide_only"), a, db)
            check("hide_only_does_not_train_broad_preferences",
                  scores(a_id)[other_roster.id] == before_a[other_roster.id]
                  and acquisition_profile(db, a_id)["custom:a"]["effective_focus"] == "interview")
            check("hidden_article_remains_visible_to_other_user", roster.id not in scores(a_id)
                  and roster.id in scores(b_id))

            source_event = add_feedback(
                FeedbackInput(item_id=stock1.id, action="not_interested", reason="source"), a, db,
            )
            check("publisher_feedback_crosses_display_labels", scores(a_id)[stock2.id] < before_a[stock2.id]
                  and scores(a_id)[stock3.id] == before_a[stock3.id])
            stock_profile = acquisition_profile(db, a_id)["stock:002491"]
            check("source_feedback_also_changes_acquisition", "eastmoney.com" not in stock_profile["search_domains"])
            try:
                undo_feedback(hidden["id"], b, db)
            except HTTPException as exc:
                check("other_user_cannot_undo_feedback", exc.status_code == 404 and roster.id not in scores(a_id))
            else:
                check("other_user_cannot_undo_feedback", False)

            try:
                add_feedback(FeedbackInput(item_id=foreign.id, action="interested"), a, db)
            except HTTPException as exc:
                check("out_of_scope_feedback_rejected", exc.status_code == 404)
            else:
                check("out_of_scope_feedback_rejected", False)

            for _ in range(5):
                add_feedback(FeedbackInput(item_id=interview.id, action="interested", reason="content_type"), a, db)
            check("memory_weight_bounded", acquisition_profile(db, a_id)["custom:a"]["weights"]["interview"] == 3)
            check("repeated_interest_has_one_reading_record", db.scalar(select(func.count()).select_from(Reading).where(
                Reading.user_id == a_id, Reading.item_id == interview.id,
            )) == 1)
            check("negative_feedback_also_marks_read", db.scalar(select(Reading.id).where(
                Reading.user_id == a_id, Reading.item_id == roster.id,
            )) is not None)
            check("reading_state_is_user_owned", db.scalar(select(Reading.id).where(Reading.user_id == b_id)) is None)

            undo_feedback(hidden["id"], a, db)
            undo_feedback(source_event["id"], a, db)
            for feedback in list(db.scalars(select(Feedback).where(
                Feedback.user_id == a_id, Feedback.undone_at.is_(None),
            ))):
                undo_feedback(feedback.id, a, db)
            check("undo_restores_scores_and_acquisition", scores(a_id) == before_a
                  and not acquisition_profile(db, a_id)["custom:a"]["weights"]
                  and "eastmoney.com" in acquisition_profile(db, a_id)["stock:002491"]["search_domains"])

        run = AgentRun(kind="web_news_search_sync", status="success", started_at=now - timedelta(hours=9),
                       finished_at=now - timedelta(hours=9), detail="{}")
        db.add(run)
        db.commit()
        with patch("information_agent.sources.now_utc", return_value=now):
            check("12h_search_interval_not_reported_stale_at_9h", state(db, run.kind, True)["status"] == "success")
        db.add_all([
            AgentRun(kind="web_news_search_sync", status="success", started_at=now, finished_at=now,
                     detail=json.dumps({"category": "gold", "entries": 7, "matched": 2, "created": 1,
                                        "search_credits": 1, "dropped": {"entity_mismatch": 3},
                                        "question": "Private fixture label"})),
            AgentRun(kind="web_news_search_sync", user_id=a_id, status="success", started_at=now,
                     detail=json.dumps({"entries": 999, "question": "Private fixture label"})),
            AgentRun(kind="web_news_search_sync", status="success", started_at=now - timedelta(days=2),
                     detail=json.dumps({"entries": 999})),
        ])
        db.commit()
        with patch("information_agent.supply_audit.now_utc", return_value=now):
            summary = daily_search_summary(db)
            check("daily_summary_excludes_private_and_other_day_runs", summary["entries"] == 7
                  and summary["completed_attempts"] == 2 and summary["date"] == "2026-10-14")
            check("daily_summary_retains_counts_without_private_text", summary["dropped"]["entity_mismatch"] == 3
                  and "Private fixture label" not in json.dumps(summary))

    with SessionLocal() as db:
        check("undo_and_reading_survive_new_session", not db.scalar(select(Feedback.id).where(
            Feedback.user_id == a_id, Feedback.undone_at.is_(None),
        )) and db.scalar(select(Reading.id).where(Reading.user_id == a_id)) is not None)
    print(json.dumps({"status": "passed", "synthetic": True, "cases": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
