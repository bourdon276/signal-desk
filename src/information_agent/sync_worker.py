"""Small fixed-source scheduler for the MVP deployment."""

import logging
import threading
import time

from information_agent.ingest_cninfo import sync as sync_cninfo
from information_agent.ingest_fed import sync as sync_fed
from information_agent.ingest_steam import sync as sync_steam

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def run_loop(stop: threading.Event | None = None) -> None:
    while stop is None or not stop.is_set():
        for name, sync in (("fed", sync_fed), ("steam_cs2", sync_steam), ("stock_announcements", sync_cninfo)):
            if stop is not None and stop.is_set():
                return
            try:
                logging.info("%s synced: %s", name, sync())
            except Exception as exc:
                logging.error("%s sync failed (%s); existing items retained", name, type(exc).__name__)
        if stop is None:
            time.sleep(3600)
        else:
            stop.wait(3600)


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
