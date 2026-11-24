"""Structured logging: JSON lines to a rotating file, concise text to the console."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOGGER_NAME = "undo"
LOG_FILE_NAME = "undo.log"
_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str | None = None) -> logging.Logger:
    if not name:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith("undo_core."):
        name = name[len("undo_core.") :]
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def setup_logging(
    log_dir: Path | None,
    *,
    level: str = "INFO",
    console: bool = False,
    max_bytes: int = 10 * 1024 * 1024,
    backups: int = 5,
) -> None:
    """Configure the ``undo`` logger. Safe to call more than once."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level.upper())
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / LOG_FILE_NAME, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)
    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        logger.addHandler(stream)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
