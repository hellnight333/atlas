from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from atlas_kernel import db
from atlas_kernel.agents.schedule_models import (
    QueueEntryStatus,
    RuntimeExecutionRecord,
    RuntimeExecutionStatus,
)
from atlas_kernel.api import app, repository, runtime
from atlas_kernel.backup import (
    BACKUP_FORMAT_VERSION,
    BackupError,
    BackupScope,
)
from atlas_kernel.config import (
    AtlasConfig,
    ConfigError,
    LogLevel,
    Profile,
    describe_profiles,
    load_config,
)
from atlas_kernel.logging_setup import SUBSYSTEMS, configure_logging, get_logger

client = TestClient(app)

diagnostics = runtime.diagnostics
backups = runtime.backup_service
recovery = runtime.recovery_service


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_default_profile_is_development() -> None:
    config = load_config(env={})
    assert config.profile is Profile.DEVELOPMENT
    assert config.log_level is LogLevel.DEBUG
    assert config.cloud_enabled is True


def test_every_profile_resolves() -> None:
    for profile in Profile:
        config = load_config(env={"ATLAS_PROFILE": profile.value})
        assert config.profile is profile


def test_production_profile_hardens_defaults() -> None:
    config = load_config(env={"ATLAS_PROFILE": "production"})
    assert config.is_production is True
    assert config.log_json is True
    assert config.integrity_check_on_startup is True
    assert config.runtime_timeout_seconds == 120.0


def test_offline_profile_disables_cloud() -> None:
    config = load_config(env={"ATLAS_PROFILE": "offline"})
    assert config.offline is True
    assert config.cloud_enabled is False


def test_portable_profile_keeps_state_beside_the_binary() -> None:
    config = load_config(env={"ATLAS_PROFILE": "portable"})
    assert config.data_dir == Path("./atlas-data")
    assert config.backup_dir == Path("./atlas-data/backups")


def test_environment_overrides_profile_defaults() -> None:
    """An operator must be able to override any profile decision."""
    config = load_config(env={"ATLAS_PROFILE": "production", "ATLAS_LOG_JSON": "false"})
    assert config.is_production is True
    assert config.log_json is False


def test_boolean_parsing_accepts_common_spellings() -> None:
    for truthy in ("1", "true", "TRUE", "yes", "on"):
        assert load_config(env={"ATLAS_OFFLINE": truthy}).offline is True
    for falsy in ("0", "false", "no", "off"):
        assert load_config(env={"ATLAS_OFFLINE": falsy}).offline is False


def test_invalid_configuration_is_rejected_with_the_variable_name() -> None:
    with pytest.raises(ConfigError, match="ATLAS_OFFLINE"):
        load_config(env={"ATLAS_OFFLINE": "maybe"})
    with pytest.raises(ConfigError, match="ATLAS_PROFILE"):
        load_config(env={"ATLAS_PROFILE": "nonsense"})
    with pytest.raises(ConfigError, match="ATLAS_LEASE_SECONDS"):
        load_config(env={"ATLAS_LEASE_SECONDS": "soon"})


def test_empty_environment_value_falls_back_to_default() -> None:
    assert load_config(env={"ATLAS_LEASE_SECONDS": ""}).lease_seconds == 120


def test_numeric_and_path_overrides() -> None:
    config = load_config(
        env={
            "ATLAS_LEASE_SECONDS": "300",
            "ATLAS_RUNTIME_TIMEOUT_SECONDS": "45.5",
            "ATLAS_DATA_DIR": "/tmp/atlas-test",
        }
    )
    assert config.lease_seconds == 300
    assert config.runtime_timeout_seconds == 45.5
    assert config.data_dir == Path("/tmp/atlas-test")


def test_profiles_are_describable_for_the_desktop() -> None:
    described = {entry["profile"] for entry in describe_profiles()}
    assert described == {p.value for p in Profile}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def test_structured_logging_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(AtlasConfig(log_json=True, log_level=LogLevel.INFO))
    get_logger("runtime").info("execution placed", extra={"execution_id": "exec-1"})

    line = capsys.readouterr().err.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["subsystem"] == "runtime"
    assert payload["message"] == "execution placed"
    assert payload["execution_id"] == "exec-1"
    assert payload["level"] == "info"


def test_human_logging_is_readable(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(AtlasConfig(log_json=False, log_level=LogLevel.INFO))
    get_logger("cluster").warning("worker offline", extra={"worker_id": "w1"})

    line = capsys.readouterr().err.strip().splitlines()[-1]
    assert "cluster" in line
    assert "worker offline" in line
    assert "worker_id=w1" in line


def test_log_level_is_respected(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(AtlasConfig(log_level=LogLevel.ERROR))
    logger = get_logger("scheduler")
    logger.info("should not appear")
    logger.error("should appear")

    captured = capsys.readouterr().err
    assert "should not appear" not in captured
    assert "should appear" in captured


def test_reconfiguring_does_not_stack_handlers() -> None:
    config = AtlasConfig()
    first = configure_logging(config)
    count = len(first.handlers)
    second = configure_logging(config)
    assert len(second.handlers) == count == 1


def test_every_subsystem_has_a_logger() -> None:
    configure_logging(AtlasConfig())
    for subsystem in SUBSYSTEMS:
        assert get_logger(subsystem).name == f"atlas.{subsystem}"


# ---------------------------------------------------------------------------
# Database hardening
# ---------------------------------------------------------------------------


def test_schema_validation_reports_healthy() -> None:
    report = db.verify_schema()
    assert report["healthy"] is True
    assert report["missing_tables"] == []
    assert report["missing_indexes"] == []
    assert report["indexes_present"] == report["indexes_expected"]


def test_every_declared_index_exists() -> None:
    assert len(db.INDEX_DEFINITIONS) >= 30
    report = db.verify_schema()
    assert report["indexes_present"] == len(db.INDEX_DEFINITIONS)


def test_index_creation_is_idempotent() -> None:
    db.init_db()
    db.init_db()
    assert db.verify_schema()["healthy"] is True


def test_integrity_check_finds_no_orphans() -> None:
    result = db.check_integrity()
    assert result["healthy"] is True
    assert all(count == 0 for count in result["orphans"].values())  # type: ignore[union-attr]


def test_schema_validation_reports_rather_than_raises() -> None:
    """A degraded database must be visible in diagnostics, not fatal at boot."""
    report = db.verify_schema()
    assert isinstance(report, dict)
    assert "healthy" in report


def test_in_process_worker_never_ages_out() -> None:
    """Regression: the local worker sends no heartbeats, so ageing it out made a
    single-machine Atlas declare its own worker dead 90 seconds after boot and
    stall every placement."""
    from atlas_kernel.cluster.models import WorkerState
    from atlas_kernel.cluster.worker_registry import LOCAL_WORKER_ID

    local = runtime.worker_registry.get(LOCAL_WORKER_ID)
    assert local is not None
    repository.upsert_worker(
        local.model_copy(update={"last_heartbeat_at": datetime.now(UTC) - timedelta(hours=6)})
    )

    stale = {w.id for w in runtime.heartbeat_service.stale_workers()}
    assert LOCAL_WORKER_ID not in stale

    offline = {w.id for w in runtime.heartbeat_service.detect_timeouts()}
    assert LOCAL_WORKER_ID not in offline

    still_online = runtime.worker_registry.get(LOCAL_WORKER_ID)
    assert still_online is not None
    assert still_online.status is not WorkerState.OFFLINE


def test_remote_workers_still_age_out() -> None:
    """The exemption must apply only to the in-process worker."""
    from atlas_kernel.cluster.models import WorkerRegistration

    worker = runtime.worker_registry.register(
        WorkerRegistration(hostname=_unique("remote"), capabilities=["image"])
    )
    repository.upsert_worker(
        worker.model_copy(update={"last_heartbeat_at": datetime.now(UTC) - timedelta(hours=6)})
    )

    assert worker.id in {w.id for w in runtime.heartbeat_service.stale_workers()}
    repository.delete_worker(worker.id)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_health_report_covers_every_component() -> None:
    report = diagnostics.health_report()
    names = {c.name for c in report.components}
    assert names == {"database", "dependencies", "providers", "workers", "runtime", "plugins"}


def test_system_information_is_populated() -> None:
    info = diagnostics.system_information()
    assert info["python_version"]
    assert info["platform"]
    assert info["hostname"]


def test_dependency_report_covers_required_packages() -> None:
    report = diagnostics.dependency_report()
    names = {d["name"] for d in report}
    assert {"fastapi", "pydantic", "sqlalchemy"} <= names
    assert all(d["installed"] for d in report if d["name"] in {"fastapi", "pydantic"})


def test_database_status_is_healthy() -> None:
    status = diagnostics.database_status()
    assert status.healthy is True
    assert status.data["schema"]["healthy"] is True


def test_provider_status_reports_adapters() -> None:
    status = diagnostics.provider_status()
    assert status.data["registered"] >= 2
    assert status.data["with_adapter"] >= 2


def test_plugin_status_is_honest_about_having_no_sdk() -> None:
    """Reporting a capability Atlas does not have would be worse than none."""
    status = diagnostics.plugin_status()
    assert status.data["sdk_available"] is False
    assert status.data["installed"] == 0


def test_environment_report_never_leaks_the_database_url() -> None:
    report = diagnostics.environment_report()
    assert "database_url" not in report
    assert report["database_configured"] is True
    assert "password" not in json.dumps(report).lower()


def test_diagnostics_export_is_shareable() -> None:
    export = diagnostics.export()
    assert {"system", "environment", "dependencies", "components"} <= set(export)
    serialized = json.dumps(export)
    assert "postgresql://" not in serialized
    assert "psycopg" not in serialized.split('"dependencies"')[0]


def test_diagnostics_api_surface() -> None:
    for path in (
        "/health/report",
        "/diagnostics",
        "/diagnostics/system",
        "/diagnostics/environment",
        "/diagnostics/dependencies",
        "/diagnostics/database",
        "/diagnostics/providers",
        "/diagnostics/workers",
        "/diagnostics/plugins",
        "/configuration",
    ):
        assert client.get(path).status_code == 200, path


def test_configuration_endpoint_lists_profiles() -> None:
    body = client.get("/configuration").json()
    assert {p["profile"] for p in body["profiles"]} == {p.value for p in Profile}
    assert "database_url" not in body["resolved"]


# ---------------------------------------------------------------------------
# Backup and restore
# ---------------------------------------------------------------------------


def _make_project() -> str:
    workspace = client.post("/workspaces", json={"name": _unique("bk-ws"), "description": "b"})
    project = client.post(
        "/projects",
        json={
            "workspace_id": workspace.json()["workspace_id"],
            "name": _unique("bk-project"),
            "description": "b",
        },
    )
    return project.json()["project_id"]


def test_project_backup_round_trips_through_json() -> None:
    project_id = _make_project()
    archive = backups.export_project(project_id)

    raw = backups.to_json(archive)
    restored = backups.from_json(raw)
    assert restored.manifest.checksum == archive.manifest.checksum
    assert restored.manifest.scope is BackupScope.PROJECT
    assert restored.manifest.scope_id == project_id


def test_backup_manifest_counts_match_contents() -> None:
    archive = backups.export_project(_make_project())
    for section, count in archive.manifest.counts.items():
        assert len(archive.data[section]) == count


def test_backup_validates_clean() -> None:
    result = backups.validate(backups.export_project(_make_project()))
    assert result.valid is True
    assert result.errors == []


def test_tampered_backup_fails_checksum() -> None:
    archive = backups.export_project(_make_project())
    archive.data["projects"][0]["name"] = "tampered"

    result = backups.validate(archive)
    assert result.valid is False
    assert any("Checksum mismatch" in e for e in result.errors)


def test_backup_with_wrong_counts_is_rejected() -> None:
    archive = backups.export_project(_make_project())
    archive.manifest.counts["projects"] = 99

    result = backups.validate(archive)
    assert result.valid is False
    assert any("declares 99" in e for e in result.errors)


def test_future_format_version_is_refused() -> None:
    archive = backups.export_project(_make_project())
    archive.manifest.format_version = BACKUP_FORMAT_VERSION + 1

    result = backups.validate(archive)
    assert result.valid is False
    assert any("newer than this build" in e for e in result.errors)


def test_restore_refuses_an_invalid_archive() -> None:
    archive = backups.export_project(_make_project())
    archive.manifest.format_version = BACKUP_FORMAT_VERSION + 5

    with pytest.raises(BackupError):
        backups.restore(archive)


def test_restore_is_idempotent_and_skips_existing_rows() -> None:
    """Restoring a backup over its own source must change nothing."""
    project_id = _make_project()
    archive = backups.export_project(project_id)

    result = backups.restore(archive)
    assert result.restored["projects"] == 0, "the project already exists"


def test_dry_run_restore_reports_without_writing() -> None:
    project_id = _make_project()
    archive = backups.export_project(project_id)
    projects_before = len(repository.list_projects())

    result = backups.restore(archive, dry_run=True)
    assert result.dry_run is True
    assert len(repository.list_projects()) == projects_before


def test_restore_recreates_a_deleted_project() -> None:
    project_id = _make_project()
    archive = backups.export_project(project_id)

    # Simulate loss by restoring into a database where the row is absent.
    archive.data["projects"][0]["id"] = _unique("restored-project")
    archive.manifest.checksum = backups._checksum(archive.data)

    result = backups.restore(archive)
    assert result.restored["projects"] == 1
    assert repository.get_project(archive.data["projects"][0]["id"]) is not None


def test_audit_records_are_never_restored() -> None:
    """Rewriting history through a backup would defeat append-only audit."""
    organization = runtime.organization_service.create_organization(name=_unique("Backup Org"))
    archive = backups.export_organization(organization.id)
    assert archive.data["audit_records"], "organization creation is audited"

    result = backups.restore(archive)
    assert "audit_records" in result.skipped
    assert "audit_records" not in result.restored


def test_settings_backup_covers_global_state() -> None:
    archive = backups.export_settings()
    assert archive.manifest.scope is BackupScope.SETTINGS
    assert {"approval_policies", "workers", "roles", "identities"} <= set(archive.data)


def test_workspace_backup_aggregates_projects() -> None:
    workspace = client.post("/workspaces", json={"name": _unique("agg-ws"), "description": "b"})
    workspace_id = workspace.json()["workspace_id"]
    client.post(
        "/projects",
        json={"workspace_id": workspace_id, "name": _unique("agg-p"), "description": "b"},
    )
    archive = backups.export_workspace(workspace_id)
    assert archive.manifest.scope is BackupScope.WORKSPACE
    assert len(archive.data["projects"]) >= 1


def test_backup_of_missing_scope_raises() -> None:
    with pytest.raises(BackupError, match="Project not found"):
        backups.export_project("project-does-not-exist")
    with pytest.raises(BackupError, match="Organization not found"):
        backups.export_organization("org-does-not-exist")


def test_malformed_json_is_rejected() -> None:
    with pytest.raises(BackupError, match="not valid JSON"):
        backups.from_json("{not json")
    with pytest.raises(BackupError, match="does not match the backup schema"):
        backups.from_json('{"unexpected": true}')


def test_backup_api_surface() -> None:
    project_id = _make_project()
    exported = client.post("/backups/export", json={"scope": "project", "scope_id": project_id})
    assert exported.status_code == 200
    archive = exported.json()

    validated = client.post("/backups/validate", json={"archive": archive})
    assert validated.status_code == 200
    assert validated.json()["valid"] is True

    restored = client.post("/backups/restore", json={"archive": archive, "dry_run": True})
    assert restored.status_code == 200
    assert restored.json()["dry_run"] is True


def test_backup_api_rejects_a_corrupt_archive() -> None:
    assert client.post("/backups/validate", json={"archive": {"bad": 1}}).status_code == 400
    assert (
        client.post("/backups/export", json={"scope": "project", "scope_id": "nope"}).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def _orphaned_execution(age_seconds: int = 3600) -> str:
    execution_id = _unique("orphan")
    stale = datetime.now(UTC) - timedelta(seconds=age_seconds)
    repository.create_runtime_execution(
        RuntimeExecutionRecord(
            execution_id=execution_id,
            schedule_id=_unique("sched"),
            entry_id=_unique("entry"),
            agent_id=_unique("agent"),
            plan_id=_unique("plan"),
            action="image.generate",
            status=RuntimeExecutionStatus.RUNNING,
            created_at=stale,
            updated_at=stale,
            heartbeat_at=stale,
        )
    )
    return execution_id


def test_orphaned_execution_is_detected() -> None:
    execution_id = _orphaned_execution()
    orphans = {e.execution_id for e in recovery.find_orphaned_executions()}
    assert execution_id in orphans


def test_fresh_execution_is_not_treated_as_orphaned() -> None:
    execution_id = _orphaned_execution(age_seconds=1)
    orphans = {e.execution_id for e in recovery.find_orphaned_executions()}
    assert execution_id not in orphans


def test_orphaned_execution_is_requeued() -> None:
    execution_id = _orphaned_execution()
    actions = recovery.recover_orphaned_executions()

    assert execution_id in {a.target_id for a in actions}
    restored = repository.get_runtime_execution(execution_id)
    assert restored is not None
    assert restored.status is RuntimeExecutionStatus.QUEUED
    assert restored.worker_id is None


def test_dry_run_recovery_changes_nothing() -> None:
    execution_id = _orphaned_execution()
    actions = recovery.recover_orphaned_executions(dry_run=True)

    assert execution_id in {a.target_id for a in actions}
    unchanged = repository.get_runtime_execution(execution_id)
    assert unchanged is not None
    assert unchanged.status is RuntimeExecutionStatus.RUNNING


def test_full_sweep_is_idempotent() -> None:
    _orphaned_execution()
    first = recovery.run_full_sweep()
    second = recovery.run_full_sweep()
    assert first.count >= 1
    assert second.count <= first.count


def test_recovery_report_is_a_dry_run() -> None:
    _orphaned_execution()
    report = recovery.run_full_sweep(dry_run=True)
    assert report.dry_run is True
    assert report.count >= 1


def test_stuck_queue_entry_is_requeued() -> None:
    from atlas_kernel.agents.plan_models import PlanStep
    from atlas_kernel.agents.schedule_models import SchedulerPriority, SchedulerRequest

    project = client.post("/workspaces", json={"name": _unique("rec-ws"), "description": "r"})
    project_id = client.post(
        "/projects",
        json={
            "workspace_id": project.json()["workspace_id"],
            "name": _unique("rec-p"),
            "description": "r",
        },
    ).json()["project_id"]
    agent_id = client.post(
        "/agents",
        json={
            "name": "Recovery Agent",
            "description": "r",
            "role": "operator",
            "project_id": project_id,
            "capabilities": ["image"],
            "permission_set": ["execute_workflow"],
        },
    ).json()["id"]

    schedule = runtime.agent_scheduler.create_schedule(
        SchedulerRequest(
            plan_id=_unique("plan"),
            agent_id=agent_id,
            steps=[
                PlanStep(
                    description="stuck",
                    capability="image",
                    action="image.generate",
                    payload={},
                    expected_output="image",
                )
            ],
            priority=SchedulerPriority.NORMAL,
            available_executors=["local"],
        )
    )
    stored = repository.get_schedule(schedule.schedule_id)
    assert stored is not None
    stored.queue_entries[0].status = QueueEntryStatus.RUNNING
    repository.update_schedule(stored)

    actions = recovery.recover_queue()
    assert stored.queue_entries[0].id in {a.target_id for a in actions}

    after = repository.get_schedule(schedule.schedule_id)
    assert after is not None
    assert after.queue_entries[0].status is QueueEntryStatus.READY


def test_recovery_api_surface() -> None:
    _orphaned_execution()
    report = client.get("/recovery/report")
    assert report.status_code == 200
    assert report.json()["dry_run"] is True

    swept = client.post("/recovery/sweep", json={"dry_run": False})
    assert swept.status_code == 200
    assert "actions" in swept.json()


def test_recovery_never_deletes_executions() -> None:
    execution_id = _orphaned_execution()
    before = len(repository.list_runtime_executions())
    recovery.run_full_sweep()
    after = len(repository.list_runtime_executions())

    assert after == before, "recovery requeues; it never discards work"
    assert repository.get_runtime_execution(execution_id) is not None


# ---------------------------------------------------------------------------
# Startup and performance smoke
# ---------------------------------------------------------------------------


def test_runtime_constructs_with_every_profile() -> None:
    from atlas_kernel.composition_root import create_runtime

    for profile in (Profile.DEVELOPMENT, Profile.PORTABLE, Profile.OFFLINE):
        built = create_runtime(config=load_config(env={"ATLAS_PROFILE": profile.value}))
        assert built.config.profile is profile
        assert built.diagnostics is not None


#: Smoke thresholds catch catastrophic regressions (orders of magnitude), not
#: micro-benchmarks. They are deliberately generous because CI runs these under
#: coverage instrumentation, where a tight bound would be flaky rather than
#: informative — and a flaky performance test is worse than none.
SMOKE_BUDGET_SECONDS = 10.0


def test_health_endpoint_is_fast() -> None:
    """A health probe that is slow is a health probe nobody runs."""
    start = time.perf_counter()
    response = client.get("/health")
    elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert elapsed < SMOKE_BUDGET_SECONDS, f"health check took {elapsed:.3f}s"


def test_diagnostics_export_completes_promptly() -> None:
    start = time.perf_counter()
    diagnostics.export()
    elapsed = time.perf_counter() - start
    assert elapsed < SMOKE_BUDGET_SECONDS, f"diagnostics export took {elapsed:.3f}s"


def test_schema_verification_is_fast() -> None:
    start = time.perf_counter()
    db.verify_schema()
    elapsed = time.perf_counter() - start
    assert elapsed < SMOKE_BUDGET_SECONDS, f"schema verification took {elapsed:.3f}s"


def test_backup_export_scales_to_a_project() -> None:
    project_id = _make_project()
    start = time.perf_counter()
    backups.export_project(project_id)
    elapsed = time.perf_counter() - start
    assert elapsed < SMOKE_BUDGET_SECONDS, f"project backup took {elapsed:.3f}s"


def test_recovery_survives_an_execution_whose_worker_is_gone() -> None:
    """A vanished worker is the situation recovery exists for.

    `_release_placement` raised `WorkerRegistryError` when the worker record had
    been removed, so `recover_orphaned_executions` aborted on the first such
    execution and requeued **none** of the others. Recovery failing hardest
    precisely when something has been lost is the wrong way round.

    Found because this test failed in isolation and passed in a full run: the
    orphan referencing a missing worker was left behind by a different test, so
    whether recovery worked depended on execution order.
    """
    missing_worker = _orphaned_execution()
    record = repository.get_runtime_execution(missing_worker)
    assert record is not None
    record.worker_id = "worker-that-was-removed"
    record.lease_id = _unique("lease")
    record.reservation_id = _unique("reservation")
    repository.update_runtime_execution(record)

    alongside = _orphaned_execution()

    actions = recovery.recover_orphaned_executions()
    recovered = {a.target_id for a in actions}
    assert missing_worker in recovered
    assert alongside in recovered, (
        "one execution with a missing worker must not stop the others being "
        "recovered")

    restored = repository.get_runtime_execution(missing_worker)
    assert restored is not None
    assert restored.status is RuntimeExecutionStatus.QUEUED
    # Cleared even though the release failed. Leaving it set would wedge the
    # execution: it could never be released, because the release is what fails.
    assert restored.lease_id is None
    assert restored.worker_id is None
