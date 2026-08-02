from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from .config import AtlasConfig, LogLevel

#: One logger per subsystem, so an operator can raise the level on exactly the
#: thing they are debugging without drowning in everything else.
SUBSYSTEMS: tuple[str, ...] = (
    "runtime",
    "scheduler",
    "worker",
    "cluster",
    "automation",
    "approval",
    "organization",
    "graph",
    "repository",
    "api",
)

_LEVELS: dict[LogLevel, int] = {
    LogLevel.DEBUG: logging.DEBUG,
    LogLevel.INFO: logging.INFO,
    LogLevel.WARNING: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
}

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class StructuredFormatter(logging.Formatter):
    """Emits one JSON object per record, with any extra=... fields inlined."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "subsystem": record.name.removeprefix("atlas."),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class HumanFormatter(logging.Formatter):
    """Readable single line for development, with extras appended as key=value."""

    def format(self, record: logging.LogRecord) -> str:
        stamp = datetime.fromtimestamp(record.created, UTC).strftime("%H:%M:%S")
        subsystem = record.name.removeprefix("atlas.")
        extras = " ".join(
            f"{key}={value}"
            for key, value in record.__dict__.items()
            if key not in _RESERVED and not key.startswith("_")
        )
        line = f"{stamp} {record.levelname.lower():<7} {subsystem:<12} {record.getMessage()}"
        return f"{line} {extras}".rstrip()


def configure_logging(config: AtlasConfig) -> logging.Logger:
    """Idempotent: re-configuring replaces handlers rather than stacking them."""
    root = logging.getLogger("atlas")
    root.setLevel(_LEVELS[config.log_level])
    root.propagate = False

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(StructuredFormatter() if config.log_json else HumanFormatter())
    root.addHandler(handler)

    for subsystem in SUBSYSTEMS:
        logging.getLogger(f"atlas.{subsystem}").setLevel(_LEVELS[config.log_level])

    return root


def get_logger(subsystem: str) -> logging.Logger:
    """Subsystem logger. Unknown names still work; they simply inherit root."""
    return logging.getLogger(f"atlas.{subsystem}")
