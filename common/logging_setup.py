from __future__ import annotations

import logging
import os

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=FORMAT, datefmt=DATEFMT)
    # Optional copy of the log in a file (run_weekly.cmd sets this), on top of the console.
    path = os.environ.get("TI_LOG_FILE")
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FORMAT, DATEFMT))
        logging.getLogger().addHandler(handler)
    # Silence chatty libraries.
    for noisy in ("httpx", "urllib3", "yfinance", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
