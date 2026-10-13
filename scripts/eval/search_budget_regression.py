"""Offline regression of paid-search limits and empty-result scheduling; no network calls."""

import asyncio
import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import patch


def main():
    with tempfile.TemporaryDirectory(prefix="signal-search-eval-") as directory:
        os.environ["DATABASE_URL"] = "sqlite:///" + directory + "/eval.db"
        os.environ["SEARCH_ENABLED"] = "true"
        os.environ["TAVILY_API_KEY"] = "offline-fixture-only"
        evaluate()


def evaluate():
    from information_agent import web_search
    from information_agent.config import settings
    from information_agent.db import Base, SessionLocal, engine
    from information_agent.models import SearchBudget, SearchCache, User, Watch
    from information_agent.search_schedule import automatic_due_at, fair_order

    settings.search_day_credit_limit = 4
    settings.search_manual_reserved_credits = 1
    settings.search_month_credit_limit = 100
    settings.search_auto_interval_hours = 12
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        user = User(email="offline@example.invalid", password_hash="not-a-login")
        db.add(user)
        db.flush()
        uid = user.id
        db.add_all(Watch(user_id=uid, watch_id=marker) for marker in (
            "stock:002491", "stock:002296", "gold:london",
        ))
        db.commit()

    class EmptyProvider:
        cache_namespace = "offline-empty"
        calls = 0

        async def search(self, *args, **kwargs):
            self.calls += 1
            return []

    adapter = EmptyProvider()
    moment = datetime(2026, 10, 14, 1, tzinfo=UTC)
    with patch.object(web_search, "provider", return_value=adapter), patch.object(
        web_search, "now_utc", return_value=moment,
    ) as clock:
        first = web_search.sync()
        assert first["search_credits"] == 3 and adapter.calls == 3
        assert first["automatic_paused"] and not first["budget_exhausted"]
        clock.return_value = moment + timedelta(hours=1)
        repeat = web_search.sync()
        assert repeat["cadence_deferred"] == 3 and repeat["due_targets"] == 0
        assert repeat["search_credits"] == 0 and adapter.calls == 3

        # Automatic cap refusal rolls back ALL reservations, including global
        # month/day counters and the cache lease.
        refused, token = web_search.claim("extra-automatic", None)
        assert refused["status"] == "budget_exhausted" and token is None
        with SessionLocal() as db:
            assert db.get(SearchBudget, "day:2026-10-14").credits == 3
            assert db.get(SearchBudget, "month:2026-10").credits == 3
            assert db.get(SearchCache, "extra-automatic") is None

        manual = asyncio.run(web_search.discover({
            "watch_id": "stock:002491", "name": "通鼎互联", "kind": "stock",
        }, user_id=uid))
        assert manual["status"] == "success" and adapter.calls == 4
        with SessionLocal() as db:
            state = web_search.search_budget_state(db, uid)
            assert state["budget_exhausted"] and state["manual_remaining"] == 0
        refused, _ = web_search.claim("extra-manual", uid)
        assert refused["status"] == "budget_exhausted"
        with SessionLocal() as db:
            assert db.get(SearchBudget, "month:2026-10").credits == 4
            assert db.get(SearchBudget, "auto_day:2026-10-14").credits == 3

        # Once credits and the interval permit, the same empty plan is retried.
        settings.search_day_credit_limit = 10
        clock.return_value = moment + timedelta(hours=13)
        next_round = web_search.sync()
        assert next_round["search_credits"] == 3 and adapter.calls == 7
        with SessionLocal() as db:
            settings.search_month_credit_limit = db.get(SearchBudget, "month:2026-10").credits
            state = web_search.search_budget_state(db, uid)
            assert state["limit_reason"] == "month" and state["automatic_remaining"] == 0
        refused, _ = web_search.claim("month-refusal", uid)
        assert refused["status"] == "budget_exhausted"

    rows = [({"watch_id": "a"}, "recent", moment), ({"watch_id": "a"}, "interview", moment),
            ({"watch_id": "b"}, "recent", moment), ({"watch_id": "c"}, "recent", moment)]
    assert {row[0]["watch_id"] for row in fair_order(rows)[:3]} == {"a", "b", "c"}
    assert automatic_due_at({"status": "failure", "completed_at": moment.isoformat()}, 12) == (
        moment + timedelta(hours=6)
    )
    print("PASS: empty-result cadence, entity fairness, manual reservation, atomic rollback, day/month caps")


if __name__ == "__main__":
    main()
