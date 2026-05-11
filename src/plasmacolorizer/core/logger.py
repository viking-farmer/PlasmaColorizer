"""Persistent file logger for diagnosing what's happening during a generate run.

Logs are written to ``~/.cache/plasmacolorizer/log.txt`` with timestamps and
process / thread identifiers so we can tell whether a step ran on the GUI
thread or the worker thread.  The file is opened in append mode and stays
useful across multiple runs; rotation is left to the user.

Why a file:
    The PyQt6 progress dialog and the Qt log widget rely on the main thread's
    event loop being responsive.  If anything blocks (DBus, subprocess) we
    might never get the on-screen progress.  A plain log file always works.
"""

from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


def log_file_path() -> Path:
    return Path(os.path.expanduser("~/.cache/plasmacolorizer/log.txt"))


_LOCK = threading.Lock()
_CONFIGURED = False


def get_logger(name: str = "plasmacolorizer") -> logging.Logger:
    """Return a process-wide logger that writes to the cache log file."""
    global _CONFIGURED
    with _LOCK:
        logger = logging.getLogger(name)
        if _CONFIGURED:
            return logger

        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        path = log_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            str(path),
            maxBytes=512 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] [pid=%(process)d tid=%(thread)d] "
            "%(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)

        stderr = logging.StreamHandler()
        stderr.setFormatter(logging.Formatter("[plasmacolorizer] %(message)s"))
        stderr.setLevel(logging.INFO)
        logger.addHandler(stderr)

        _CONFIGURED = True
        return logger
