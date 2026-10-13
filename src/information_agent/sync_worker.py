"""Small fixed-source scheduler for the MVP deployment."""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from information_agent.db import SessionLocal
from information_agent.ingest_articles import sync as sync_articles
from information_agent.ingest_cninfo import sync as sync_cninfo
from information_agent.ingest_fed import sync as sync_fed
from information_agent.ingest_pandascore import sync as sync_pandascore
from information_agent.ingest_perfect_news import sync as sync_perfect_news
from information_agent.ingest_team_news import sync as sync_team_news
from information_agent.ingest_team_news import sync_dust2
from information_agent.models import AgentRun, now_utc
from information_agent.web_search import sync as sync_web_news

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SYNCERS = {
    "fed": sync_fed,
    "cs2_team_matches": sync_pandascore,
    "cs2_team_news": sync_team_news,
    "dust2_br_news": sync_dust2,
    "perfect_world_news": sync_perfect_news,
    "stock_announcements": sync_cninfo,
    "web_news": sync_web_news,
}
_SOURCE_LOCKS = {name: threading.Lock() for name in SYNCERS}
_ROUND_LOCK = threading.Lock()
_ARTICLE_LOCK = threading.Lock()
_REQUESTED: set[str] = set()
_REQUEST_LOCK = threading.Lock()
_REQUEST_WAKE = threading.Event()


def request_sync(name: str) -> bool:
    """Queue a bounded source sync after a user adds an entity subscription."""
    if name not in SYNCERS:
        return False
    with _REQUEST_LOCK:
        _REQUESTED.add(name)
    _REQUEST_WAKE.set()
    return True


def _run_source(name: str) -> dict:
    # The scheduled request and the in-web loop share fixed-source locks.
    if not _SOURCE_LOCKS[name].acquire(blocking=False):
        return {"status": "running"}
    try:
        result = SYNCERS[name]()
        logging.info("%s synced: %s", name, result)
        return result
    except Exception as exc:
        logging.error("%s sync failed (%s); existing items retained", name, type(exc).__name__)
        return {"status": "failure", "error_type": type(exc).__name__}
    finally:
        _SOURCE_LOCKS[name].release()


def _run_sources(names) -> dict:
    names = tuple(names)
    # Only two concurrent sources on the small web instance; each owns its DB session.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="collect") as pool:
        results = dict(zip(names, pool.map(_run_source, names), strict=True))
    # Wait for search and RSS inserts before preparing article bodies. Runs even
    # when search is disabled or out of credits; only known article URLs are read.
    if _ARTICLE_LOCK.acquire(blocking=False):
        try:
            results["article_bodies"] = sync_articles()
        except Exception as exc:
            results["article_bodies"] = {"status": "failure", "error_type": type(exc).__name__}
        finally:
            _ARTICLE_LOCK.release()
    else:
        results["article_bodies"] = {"status": "running"}
    return results


def run_once() -> dict:
    if not _ROUND_LOCK.acquire(blocking=False):
        with SessionLocal() as db:
            active = db.scalar(select(AgentRun).where(
                AgentRun.kind == "scheduled_collection", AgentRun.status == "running",
            ).order_by(AgentRun.started_at.desc()).limit(1))
            return {"status": "running", "run_id": active.id if active else None,
                    "message": "已有采集轮次正在执行"}
    try:
        with SessionLocal() as db:
            run = AgentRun(kind="scheduled_collection", status="running", detail="")
            db.add(run)
            db.commit()
            run_id = run.id
        results = _run_sources(SYNCERS)
        failed = any(row.get("status") in {"failure", "partial"} for row in results.values())
        status = "partial" if failed else "success"
        with SessionLocal() as db:
            run = db.get(AgentRun, run_id)
            run.status = status
            run.finished_at = now_utc()
            run.detail = json.dumps(results, ensure_ascii=False)
            db.commit()
        return {"status": status, "run_id": run_id, "sources": results}
    finally:
        _ROUND_LOCK.release()


def run_loop(stop: threading.Event | None = None) -> None:
    while stop is None or not stop.is_set():
        try:
            run_once()
        except Exception as exc:
            logging.error("collection round failed (%s); next round will retry", type(exc).__name__)
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            if stop is not None and stop.is_set():
                return
            if _REQUEST_WAKE.wait(timeout=min(1, deadline - time.monotonic())):
                _REQUEST_WAKE.clear()
                with _REQUEST_LOCK:
                    requested = set(_REQUESTED)
                    _REQUESTED.clear()
                if requested:
                    if stop is not None and stop.is_set():
                        return
                    _run_sources(sorted(requested))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Collect fixed public news sources")
    parser.add_argument("--once", action="store_true", help="Run one collection round, then exit")
    if parser.parse_args().once:
        print(json.dumps(run_once(), ensure_ascii=False))
    else:
        run_loop()


if __name__ == "__main__":
    main()
