"""Telemetry -- off unless the operator turns it on.

Three rules shape this module:

1. **Disabled by default.** A fresh install sends nothing. Consent is a
   deliberate act, recorded with a timestamp, and revocable.
2. **No user content, ever.** Payloads are built from an allow-list of keys
   (:data:`ALLOWED_EVENT_FIELDS`). A deny-list would leak the first time
   someone added a field; an allow-list cannot.
3. **Nothing is sent anywhere by default.** Atlas operates no telemetry
   server. The default sink writes to a local file the operator can read.
   Shipping a network sink is a deployment decision, not a default.

Crash reports follow the same rules: exception *type* and a sanitised
traceback shape, never the message, never local variables, never paths
outside the Atlas package.
"""

from __future__ import annotations

import json
import platform
import re
import traceback
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from atlas_kernel.config import TelemetryMode
from atlas_kernel.logging_setup import get_logger
from atlas_kernel.version import CHANNEL, VERSION

logger = get_logger("telemetry")


#: The complete set of keys that may appear in a telemetry event. Anything
#: else is dropped before the event is built. This is the privacy guarantee:
#: a new field cannot leak until it is added here deliberately.
ALLOWED_EVENT_FIELDS: frozenset[str] = frozenset(
    {
        "event",
        "install_id",
        "timestamp",
        "version",
        "channel",
        "os",
        "os_release",
        "arch",
        "python_version",
        "profile",
        "exception_type",
        "exception_module",
        "frame_count",
        "atlas_frames",
        "component",
        "duration_ms",
        "count",
        "outcome",
    }
)

#: Traceback frames are reduced to ``module:function:line`` and only when the
#: file lives inside the Atlas package. A user's home directory, project name
#: or asset filename must never reach a crash report.
_ATLAS_PATH = re.compile(r"atlas_kernel[/\\]([\w/\\]+)\.py$")


class TelemetrySink(Protocol):
    """Where events go. Implementations must not raise."""

    def emit(self, event: dict[str, Any]) -> None: ...


class NullSink:
    """Accepts and discards. Used when telemetry is disabled."""

    def emit(self, event: dict[str, Any]) -> None:  # noqa: D102
        return None


class FileSink:
    """Appends one JSON object per line to a local file.

    This is the default sink. The operator can read exactly what was
    collected, which is the point -- telemetry you cannot inspect is telemetry
    you cannot trust.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def emit(self, event: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
        except OSError as exc:
            # Telemetry must never take the application down with it.
            logger.warning("telemetry write failed", extra={"reason": str(exc)})


@dataclass(frozen=True)
class TelemetryConsent:
    """A recorded decision. ``None`` for decided_at means never asked."""

    mode: TelemetryMode = TelemetryMode.DISABLED
    decided_at: datetime | None = None
    install_id: str | None = None

    @property
    def asked(self) -> bool:
        return self.decided_at is not None

    @property
    def collects_crashes(self) -> bool:
        return self.mode in (TelemetryMode.CRASH_ONLY, TelemetryMode.DIAGNOSTICS)

    @property
    def collects_diagnostics(self) -> bool:
        return self.mode is TelemetryMode.DIAGNOSTICS

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": str(self.mode),
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "install_id": self.install_id,
            "asked": self.asked,
        }


def sanitise_traceback(exc: BaseException) -> list[str]:
    """Reduce a traceback to Atlas-internal frames only.

    Returns entries like ``agents/runtime:execute_entry:214``. Frames from
    site-packages, the standard library or user scripts are dropped -- their
    paths can contain a username, a project name or a file the user created.
    """
    frames: list[str] = []
    for frame in traceback.extract_tb(exc.__traceback__):
        match = _ATLAS_PATH.search(frame.filename)
        if match is None:
            continue
        module = match.group(1).replace("\\", "/")
        frames.append(f"{module}:{frame.name}:{frame.lineno}")
    return frames


def _filter(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop every key that is not explicitly allowed."""
    return {k: v for k, v in payload.items() if k in ALLOWED_EVENT_FIELDS}


class TelemetryService:
    """Collects only what consent covers, and only into the configured sink."""

    def __init__(
        self,
        consent: TelemetryConsent | None = None,
        sink: TelemetrySink | None = None,
        profile: str = "development",
    ) -> None:
        self._consent = consent or TelemetryConsent()
        self._sink = sink or NullSink()
        self._profile = profile

    @property
    def consent(self) -> TelemetryConsent:
        return self._consent

    @property
    def enabled(self) -> bool:
        return self._consent.mode is not TelemetryMode.DISABLED

    def set_consent(self, mode: TelemetryMode, now: datetime | None = None) -> TelemetryConsent:
        """Record a decision.

        Enabling generates a random install id; disabling discards it, so
        revoking consent also destroys the only identifier that existed.
        """
        stamp = now or datetime.now(UTC)
        if mode is TelemetryMode.DISABLED:
            self._consent = TelemetryConsent(mode=mode, decided_at=stamp, install_id=None)
        else:
            install_id = self._consent.install_id or uuid.uuid4().hex
            self._consent = TelemetryConsent(mode=mode, decided_at=stamp, install_id=install_id)
        logger.info("telemetry consent set", extra={"mode": str(mode)})
        return self._consent

    def _base(self, event: str, now: datetime | None = None) -> dict[str, Any]:
        return {
            "event": event,
            "install_id": self._consent.install_id,
            "timestamp": (now or datetime.now(UTC)).isoformat(),
            "version": VERSION,
            "channel": CHANNEL,
        }

    def record_version(self, now: datetime | None = None) -> dict[str, Any] | None:
        """Anonymous version + platform ping. Requires diagnostics consent."""
        if not self._consent.collects_diagnostics:
            return None
        payload = _filter(
            {
                **self._base("version", now),
                "os": platform.system(),
                "os_release": platform.release(),
                "arch": platform.machine(),
                "python_version": platform.python_version(),
                "profile": self._profile,
            }
        )
        self._sink.emit(payload)
        return payload

    def record_crash(
        self,
        exc: BaseException,
        component: str = "unknown",
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Anonymous crash report. Requires at least crash consent.

        The exception *message* is deliberately excluded: messages routinely
        contain paths, identifiers and user input.
        """
        if not self._consent.collects_crashes:
            return None
        frames = sanitise_traceback(exc)
        payload = _filter(
            {
                **self._base("crash", now),
                "exception_type": type(exc).__name__,
                "exception_module": type(exc).__module__,
                "frame_count": len(frames),
                "atlas_frames": frames,
                "component": component,
                "os": platform.system(),
                "arch": platform.machine(),
            }
        )
        self._sink.emit(payload)
        return payload

    def record_usage(
        self,
        component: str,
        outcome: str,
        duration_ms: float | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Anonymous counter. Requires diagnostics consent.

        Takes a component name and an outcome, never a payload -- there is no
        parameter through which user content could arrive.
        """
        if not self._consent.collects_diagnostics:
            return None
        payload = _filter(
            {
                **self._base("usage", now),
                "component": component,
                "outcome": outcome,
                "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
            }
        )
        self._sink.emit(payload)
        return payload

    def report(self) -> dict[str, Any]:
        """What telemetry is doing right now, for the settings screen."""
        return {
            "consent": self._consent.to_dict(),
            "enabled": self.enabled,
            "sink": type(self._sink).__name__,
            "remote_endpoint": None,
            "collects": {
                "crashes": self._consent.collects_crashes,
                "diagnostics": self._consent.collects_diagnostics,
                "user_content": False,
            },
            "allowed_fields": sorted(ALLOWED_EVENT_FIELDS),
        }
