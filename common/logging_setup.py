from __future__ import annotations

import logging
import os

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


_done = False


def setup(level: int = logging.INFO) -> None:
    global _done
    if _done:  # one script can call another's main(); don't add a second file handler
        return
    _done = True
    logging.basicConfig(level=level, format=FORMAT, datefmt=DATEFMT)
    # Optional copy of the log in a file (run_weekly.cmd sets this), on top of the console.
    path = os.environ.get("TI_LOG_FILE")
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FORMAT, DATEFMT))
        logging.getLogger().addHandler(handler)
    # Silence chatty libraries.
    for noisy in ("httpx", "httpx2", "urllib3", "yfinance", "peewee", "sentence_transformers", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # SEC filings are XHTML; parsing them as HTML is intended, so don't print bs4's long advice.
    import warnings

    try:
        from bs4 import XMLParsedAsHTMLWarning

        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    except ImportError:
        pass
