"""Small fixed-source scheduler for the MVP deployment."""

import logging
import threading
import time

from information_agent.ingest_cninfo import sync as sync_cninfo
from information_agent.ingest_fed import sync as sync_fed
from information_agent.ingest_pandascore import sync as sync_pandascore
from information_agent.ingest_team_news import sync as sync_team_news
from information_agent.web_search import sync as sync_web_news

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SYNCERS = {
    "fed": sync_fed,
    "cs2_team_matches": sync_pandascore,
    "cs2_team_news": sync_team_news,
    "stock_announcements": sync_cninfo,
    "web_news": sync_web_news,
}
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


def _run_sources(names) -> None:
    for name in names:
        try:
            logging.info("%s synced: %s", name, SYNCERS[name]())
        except Exception as exc:
            logging.error("%s sync failed (%s); existing items retained", name, type(exc).__name__)


def run_loop(stop: threading.Event | None = None) -> None:
    while stop is None or not stop.is_set():
        _run_sources(tuple(SYNCERS))
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
    run_loop()


if __name__ == "__main__":
    main()
