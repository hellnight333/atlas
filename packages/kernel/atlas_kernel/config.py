from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Profile(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    PORTABLE = "portable"
    OFFLINE = "offline"


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TelemetryMode(StrEnum):
    """What the operator has consented to collect. Ordered least to most.

    Defined here rather than in ``telemetry`` because ``config`` sits at the
    bottom of the import graph: ``logging_setup`` imports it, and ``telemetry``
    imports ``logging_setup``.
    """

    DISABLED = "disabled"
    """Nothing is collected. The default."""

    CRASH_ONLY = "crash_only"
    """Anonymous crash reports. No usage events."""

    DIAGNOSTICS = "diagnostics"
    """Crash reports plus anonymous version and environment reporting."""


class AtlasConfig(BaseModel):
    """Declarative runtime configuration.

    Every field has a default that makes a fresh checkout work, and every field
    can be overridden by one environment variable. There is no imperative
    configuration code anywhere else in the kernel.
    """

    profile: Profile = Profile.DEVELOPMENT
    database_url: str = "postgresql+psycopg://atlas:atlas@localhost:5432/atlas"

    log_level: LogLevel = LogLevel.INFO
    log_json: bool = False

    #: Offline mode refuses cloud executors; the queue keeps accepting work.
    offline: bool = False
    allow_cloud_providers: bool = True

    heartbeat_timeout_seconds: int = 90
    lease_seconds: int = 120
    runtime_timeout_seconds: float = 30.0

    #: Portable installs keep all state beside the binary.
    data_dir: Path = Path("./.atlas")
    backup_dir: Path = Path("./.atlas/backups")

    schema_validation_on_startup: bool = True
    integrity_check_on_startup: bool = False

    #: Telemetry is off unless the operator turns it on. No profile enables
    #: it -- not even production -- because consent belongs to a person, not
    #: to a deployment environment.
    telemetry_mode: TelemetryMode = TelemetryMode.DISABLED

    #: An online update check is a network call, so it is opt-in too. Atlas
    #: never checks for updates on its own.
    update_check_enabled: bool = False

    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_production(self) -> bool:
        return self.profile is Profile.PRODUCTION

    @property
    def cloud_enabled(self) -> bool:
        return self.allow_cloud_providers and not self.offline


#: Profile defaults. A profile is data: adding one never means editing logic.
PROFILE_DEFAULTS: dict[Profile, dict[str, Any]] = {
    Profile.DEVELOPMENT: {
        "log_level": LogLevel.DEBUG,
        "log_json": False,
        "schema_validation_on_startup": True,
        "integrity_check_on_startup": False,
    },
    Profile.STAGING: {
        "log_level": LogLevel.INFO,
        "log_json": True,
        "schema_validation_on_startup": True,
        "integrity_check_on_startup": True,
    },
    Profile.PRODUCTION: {
        "log_level": LogLevel.INFO,
        "log_json": True,
        "schema_validation_on_startup": True,
        "integrity_check_on_startup": True,
        "runtime_timeout_seconds": 120.0,
    },
    Profile.PORTABLE: {
        "log_level": LogLevel.INFO,
        "log_json": False,
        "data_dir": Path("./atlas-data"),
        "backup_dir": Path("./atlas-data/backups"),
        "integrity_check_on_startup": False,
    },
    Profile.OFFLINE: {
        "log_level": LogLevel.INFO,
        "log_json": False,
        "offline": True,
        "allow_cloud_providers": False,
        "integrity_check_on_startup": False,
    },
}


#: Environment variable -> (field, parser). The only place env parsing happens.
_ENV_BINDINGS: dict[str, tuple[str, str]] = {
    "ATLAS_PROFILE": ("profile", "profile"),
    "ATLAS_DATABASE_URL": ("database_url", "str"),
    "ATLAS_LOG_LEVEL": ("log_level", "log_level"),
    "ATLAS_LOG_JSON": ("log_json", "bool"),
    "ATLAS_OFFLINE": ("offline", "bool"),
    "ATLAS_ALLOW_CLOUD_PROVIDERS": ("allow_cloud_providers", "bool"),
    "ATLAS_HEARTBEAT_TIMEOUT_SECONDS": ("heartbeat_timeout_seconds", "int"),
    "ATLAS_LEASE_SECONDS": ("lease_seconds", "int"),
    "ATLAS_RUNTIME_TIMEOUT_SECONDS": ("runtime_timeout_seconds", "float"),
    "ATLAS_DATA_DIR": ("data_dir", "path"),
    "ATLAS_BACKUP_DIR": ("backup_dir", "path"),
    "ATLAS_SCHEMA_VALIDATION": ("schema_validation_on_startup", "bool"),
    "ATLAS_INTEGRITY_CHECK": ("integrity_check_on_startup", "bool"),
    "ATLAS_TELEMETRY": ("telemetry_mode", "telemetry_mode"),
    "ATLAS_UPDATE_CHECK": ("update_check_enabled", "bool"),
}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(ValueError):
    pass


def _parse(raw: str, kind: str, env_name: str) -> Any:
    try:
        if kind == "bool":
            lowered = raw.strip().lower()
            if lowered in _TRUE:
                return True
            if lowered in _FALSE:
                return False
            raise ConfigError(f"{env_name} must be a boolean, got {raw!r}")
        if kind == "int":
            return int(raw)
        if kind == "float":
            return float(raw)
        if kind == "path":
            return Path(raw)
        if kind == "profile":
            return Profile(raw.strip().lower())
        if kind == "log_level":
            return LogLevel(raw.strip().lower())
        if kind == "telemetry_mode":
            return TelemetryMode(raw.strip().lower())
        return raw
    except ConfigError:
        raise
    except ValueError as exc:
        raise ConfigError(f"{env_name} is invalid: {exc}") from exc


def load_config(env: dict[str, str] | None = None) -> AtlasConfig:
    """Resolution order: field default -> profile default -> environment.

    Environment always wins, so an operator can override any profile decision
    without editing a profile.
    """
    env = env if env is not None else dict(os.environ)

    raw_profile = env.get("ATLAS_PROFILE", Profile.DEVELOPMENT.value)
    profile = _parse(raw_profile, "profile", "ATLAS_PROFILE")

    values: dict[str, Any] = {"profile": profile}
    values.update(PROFILE_DEFAULTS.get(profile, {}))

    for env_name, (field, kind) in _ENV_BINDINGS.items():
        if env_name == "ATLAS_PROFILE":
            continue
        raw = env.get(env_name)
        if raw is not None and raw != "":
            values[field] = _parse(raw, kind, env_name)

    return AtlasConfig(**values)


def describe_profiles() -> list[dict[str, Any]]:
    """Rendered by the desktop so an operator can see what each profile does."""
    return [
        {
            "profile": profile.value,
            "defaults": {
                key: (str(value) if isinstance(value, Path) else value)
                for key, value in defaults.items()
            },
        }
        for profile, defaults in PROFILE_DEFAULTS.items()
    ]
