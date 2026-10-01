"""Small fixed-source scheduler for the MVP deployment."""

import logging
import threading
import time

from information_agent.ingest_fed import sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def run_loop(stop: threading.Event | None = None) -> None:
    while stop is None or not stop.is_set():
        try:
            result = sync()
            logging.info("Federal Reserve RSS synced: %s", result)
        except Exception:
            logging.exception("Federal Reserve RSS sync failed; existing items remain available")
        if stop is None:
            time.sleep(3600)
        else:
            stop.wait(3600)


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
