"""Logging setup.

Logs always go to ``stderr`` (never ``stdout`` — on the stdio transport that carries the MCP
protocol and would be corrupted). Optionally a rotating file log is added so a customer running
the server on their own machine has a durable artifact to send for support.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False
_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(
    level: int | str = logging.INFO,
    log_file: Path | None = None,
    *,
    max_bytes: int = 1_000_000,
    backup_count: int = 5,
) -> None:
    """Configure root logging to stderr, plus an optional rotating file. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    formatter = logging.Formatter(_FORMAT)
    root = logging.getLogger()
    root.handlers.clear()

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:  # never let logging setup take the server down
            root.warning("Could not open log file %s: %s", log_file, exc)

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(level)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
