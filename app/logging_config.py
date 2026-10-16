"""Structured logging setup."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:  # avoid duplicate handlers on reload
        return
    handler = logging.StreamHandler(sys.stdout)
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Quiet noisy libraries.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
