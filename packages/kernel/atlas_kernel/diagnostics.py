from __future__ import annotations

import platform
import sys
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from . import db
from .config import AtlasConfig

if TYPE_CHECKING:
    from .cluster.cluster_state import ClusterStateService
    from .providers import ProviderManager
    from .registry import Registry
    from .repository import AtlasRepository

#: Packages the kernel genuinely needs. Reported present/absent with version.
REQUIRED_DEPENDENCIES: tuple[str, ...] = (
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "psycopg",
    "uvicorn",
    "httpx",
)


class ComponentStatus(BaseModel):
    name: str
    healthy: bool
    detail: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class HealthReport(BaseModel):
    healthy: bool
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    components: list[ComponentStatus] = Field(default_factory=list)

    @property
    def failing(self) -> list[str]:
        return [c.name for c in self.components if not c.healthy]


class DiagnosticsService:
    """Read-only. Every method reports; none of them repair anything.

    A degraded subsystem shows up here rather than preventing startup, so an
    operator can see the whole picture before deciding what to do.
    """

    def __init__(
        self,
        config: AtlasConfig,
        repository: AtlasRepository,
        registry: Registry,
        provider_manager: ProviderManager,
        cluster_state: ClusterStateService,
    ) -> None:
        self.config = config
        self.repository = repository
        self.registry = registry
        self.provider_manager = provider_manager
        self.cluster_state = cluster_state

    # ------------------------------------------------------------------
    # Individual reports
    # ------------------------------------------------------------------

    def system_information(self) -> dict[str, Any]:
        return {
            "python_version": sys.version.split()[0],
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "hostname": platform.node(),
        }

    def environment_report(self) -> dict[str, Any]:
        return {
            "profile": self.config.profile.value,
            "offline": self.config.offline,
            "cloud_enabled": self.config.cloud_enabled,
            "log_level": self.config.log_level.value,
            "log_json": self.config.log_json,
            "data_dir": str(self.config.data_dir),
            "backup_dir": str(self.config.backup_dir),
            # Never echo the database URL: it can carry credentials.
            "database_configured": bool(self.config.database_url),
        }

    def dependency_report(self) -> list[dict[str, Any]]:
        report: list[dict[str, Any]] = []
        for name in REQUIRED_DEPENDENCIES:
            try:
                report.append(
                    {"name": name, "installed": True, "version": importlib_metadata.version(name)}
                )
            except importlib_metadata.PackageNotFoundError:
                report.append({"name": name, "installed": False, "version": None})
        return report

    def database_status(self) -> ComponentStatus:
        try:
            schema = db.verify_schema()
        except Exception as exc:  # noqa: BLE001 - diagnostics must not raise
            return ComponentStatus(
                name="database", healthy=False, detail=f"unreachable: {exc}", data={}
            )

        integrity: dict[str, Any] = {"healthy": True, "orphans": {}, "checked": False}
        if self.config.integrity_check_on_startup:
            try:
                integrity = {**db.check_integrity(), "checked": True}
            except Exception as exc:  # noqa: BLE001
                integrity = {"healthy": False, "error": str(exc), "checked": True}

        healthy = bool(schema["healthy"]) and bool(integrity["healthy"])
        missing = len(schema["missing_tables"]) + len(schema["missing_indexes"])  # type: ignore[arg-type]
        return ComponentStatus(
            name="database",
            healthy=healthy,
            detail="ok" if healthy else f"{missing} schema object(s) missing",
            data={"schema": schema, "integrity": integrity},
        )

    def provider_status(self) -> ComponentStatus:
        specs = self.registry.list_providers()
        adapters = [s for s in specs if self.provider_manager.get_adapter(s.name) is not None]
        missing = [s.name for s in specs if self.provider_manager.get_adapter(s.name) is None]
        return ComponentStatus(
            name="providers",
            healthy=not missing,
            detail="ok" if not missing else f"no adapter for: {', '.join(missing)}",
            data={
                "registered": len(specs),
                "with_adapter": len(adapters),
                "missing_adapters": missing,
                "cloud_enabled": self.config.cloud_enabled,
            },
        )

    def worker_status(self) -> ComponentStatus:
        health = self.cluster_state.health()
        load = self.cluster_state.load()
        return ComponentStatus(
            name="workers",
            healthy=health.healthy,
            detail=(
                "ok"
                if health.healthy
                else f"{len(health.stale_heartbeats)} stale, {health.offline} offline"
            ),
            data={
                "total": health.total_workers,
                "online": health.online,
                "offline": health.offline,
                "stale_heartbeats": health.stale_heartbeats,
                "expired_leases": health.expired_leases,
                "capacity": f"{load.used_capacity}/{load.total_capacity}",
            },
        )

    def plugin_status(self) -> ComponentStatus:
        """Atlas ships no plugin SDK yet; reported honestly rather than faked."""
        return ComponentStatus(
            name="plugins",
            healthy=True,
            detail="no plugin SDK in this build",
            data={"installed": 0, "sdk_available": False},
        )

    def runtime_status(self) -> ComponentStatus:
        executions = self.repository.list_runtime_executions()
        by_status: dict[str, int] = {}
        for execution in executions:
            by_status[execution.status.value] = by_status.get(execution.status.value, 0) + 1

        stuck = by_status.get("waiting_placement", 0)
        return ComponentStatus(
            name="runtime",
            healthy=True,
            detail="ok" if not stuck else f"{stuck} execution(s) awaiting placement",
            data={"total": len(executions), "by_status": by_status},
        )

    def dependency_status(self) -> ComponentStatus:
        report = self.dependency_report()
        missing = [d["name"] for d in report if not d["installed"]]
        return ComponentStatus(
            name="dependencies",
            healthy=not missing,
            detail="ok" if not missing else f"missing: {', '.join(missing)}",
            data={"packages": report},
        )

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------

    def health_report(self) -> HealthReport:
        components = [
            self.database_status(),
            self.dependency_status(),
            self.provider_status(),
            self.worker_status(),
            self.runtime_status(),
            self.plugin_status(),
        ]
        return HealthReport(
            healthy=all(c.healthy for c in components),
            components=components,
        )

    def export(self) -> dict[str, Any]:
        """Everything an operator would paste into a bug report. Contains no
        secrets: the database URL is reduced to a boolean."""
        report = self.health_report()
        return {
            "generated_at": report.generated_at.isoformat(),
            "healthy": report.healthy,
            "failing_components": report.failing,
            "system": self.system_information(),
            "environment": self.environment_report(),
            "dependencies": self.dependency_report(),
            "components": [c.model_dump(mode="json") for c in report.components],
        }
