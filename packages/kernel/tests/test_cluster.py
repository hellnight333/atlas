from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from atlas_kernel.agents.plan_models import PlanStep
from atlas_kernel.agents.schedule_models import (
    QueueEntryStatus,
    RuntimeExecutionStatus,
    SchedulerPriority,
    SchedulerRequest,
)
from atlas_kernel.api import app, repository, runtime
from atlas_kernel.cluster.events import (
    ExecutionAssigned,
    ExecutionRecovered,
    LeaseExpired,
    ReservationCreated,
    WorkerRegistered,
)
from atlas_kernel.cluster.lease_manager import LeaseManagerError
from atlas_kernel.cluster.models import (
    LeaseState,
    ReservationState,
    WorkerRegistration,
    WorkerResources,
    WorkerState,
)
from atlas_kernel.cluster.worker_registry import LOCAL_WORKER_ID, WorkerRegistryError

client = TestClient(app)

KERNEL_ROOT = Path(__file__).resolve().parents[1] / "atlas_kernel"

registry = runtime.worker_registry
heartbeats = runtime.heartbeat_service
leases = runtime.lease_manager
dispatcher = runtime.dispatcher
cluster_state = runtime.cluster_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_cluster() -> None:
    """Leaves only the local worker, so each test starts from a known cluster."""
    for worker in repository.list_workers():
        if worker.id != LOCAL_WORKER_ID:
            repository.delete_worker(worker.id)
    local = registry.get(LOCAL_WORKER_ID)
    if local is not None:
        repository.upsert_worker(
            local.model_copy(
                update={
                    "status": WorkerState.ONLINE,
                    "current_load": 0,
                    "last_heartbeat_at": datetime.now(UTC),
                }
            )
        )


def _register(name: str, capabilities: list[str], **overrides: object) -> str:
    payload: dict[str, object] = {
        "hostname": name,
        "display_name": name,
        "capabilities": capabilities,
        "max_concurrency": 1,
    }
    payload.update(overrides)
    worker = registry.register(WorkerRegistration(**payload))  # type: ignore[arg-type]
    return worker.id


def _create_project() -> str:
    ws = client.post("/workspaces", json={"name": "cluster-ws", "description": "c"})
    project = client.post(
        "/projects",
        json={
            "workspace_id": ws.json()["workspace_id"],
            "name": "cluster-project",
            "description": "c",
        },
    )
    return project.json()["project_id"]


def _create_agent(project_id: str) -> str:
    agent = client.post(
        "/agents",
        json={
            "name": "Cluster Agent",
            "description": "c",
            "role": "operator",
            "project_id": project_id,
            "capabilities": ["image"],
            "permission_set": ["execute_workflow"],
        },
    )
    return agent.json()["id"]


def _schedule(agent_id: str, payload: dict | None = None, capability: str = "image") -> str:
    step = PlanStep(
        description="cluster step",
        capability=capability,
        action="image.generate",
        payload={"prompt": "distributed", **(payload or {})},
        expected_output="image",
    )
    schedule = runtime.agent_scheduler.create_schedule(
        SchedulerRequest(
            plan_id=f"plan-{agent_id[:8]}",
            agent_id=agent_id,
            steps=[step],
            priority=SchedulerPriority.NORMAL,
            available_executors=["local"],
        )
    )
    return schedule.schedule_id


# ---------------------------------------------------------------------------
# Worker registration
# ---------------------------------------------------------------------------


def test_local_worker_is_registered_automatically() -> None:
    local = registry.get(LOCAL_WORKER_ID)
    assert local is not None
    assert local.status is WorkerState.ONLINE
    assert "image" in local.capabilities


def test_worker_registers_with_full_profile() -> None:
    _reset_cluster()
    worker = registry.register(
        WorkerRegistration(
            hostname="office-a6000",
            display_name="Office-A6000",
            platform="Ubuntu 24.04",
            resources=WorkerResources(
                cpu_cores=32, ram_gb=128, gpu="A6000", vram_gb=48, storage_gb=4000
            ),
            capabilities=["image", "video", "training"],
            max_concurrency=2,
            version="1.0.0",
            tags=["office", "gpu"],
        )
    )
    assert worker.status is WorkerState.ONLINE
    assert worker.resources.vram_gb == 48
    assert worker.max_concurrency == 2
    assert "training" in worker.capabilities

    stored = repository.get_worker(worker.id)
    assert stored is not None
    assert stored.display_name == "Office-A6000"
    assert stored.tags == ["office", "gpu"]


def test_registration_is_idempotent_per_hostname() -> None:
    _reset_cluster()
    first = registry.register(WorkerRegistration(hostname="home-lab", capabilities=["image"]))
    second = registry.register(
        WorkerRegistration(hostname="home-lab", capabilities=["image", "video"])
    )
    assert first.id == second.id, "a reconnecting worker must keep its identity"
    assert second.capabilities == ["image", "video"]
    assert len([w for w in repository.list_workers() if w.hostname == "home-lab"]) == 1


def test_worker_state_transitions() -> None:
    _reset_cluster()
    worker_id = _register("laptop", ["text"])

    assert registry.pause(worker_id).status is WorkerState.PAUSED
    assert registry.resume(worker_id).status is WorkerState.ONLINE
    assert registry.drain(worker_id).status is WorkerState.DRAINING
    assert registry.mark_offline(worker_id).status is WorkerState.OFFLINE
    assert registry.mark_error(worker_id, "gpu fault").status is WorkerState.ERROR


def test_unknown_worker_raises() -> None:
    with pytest.raises(WorkerRegistryError, match="Worker not found"):
        registry.pause("worker-does-not-exist")


def test_registration_emits_event() -> None:
    from atlas_kernel.api import event_bus

    seen: list[WorkerRegistered] = []
    event_bus.subscribe(WorkerRegistered, seen.append)

    _reset_cluster()
    _register("cloud-gpu-01", ["image"])
    assert seen
    assert seen[-1].hostname == "cloud-gpu-01"


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def test_heartbeat_updates_liveness_and_metrics() -> None:
    _reset_cluster()
    worker_id = _register("office-4090", ["image"])

    response = client.post(
        "/workers/heartbeat",
        json={
            "worker_id": worker_id,
            "current_load": 1,
            "metrics": {"gpu_percent": 71.5, "vram_used_gb": 12.0},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["current_load"] == 1
    assert body["metrics"]["gpu_percent"] == 71.5
    assert body["last_heartbeat_at"] is not None

    history = heartbeats.history(worker_id)
    assert history and history[0].metrics.gpu_percent == 71.5


def test_stale_worker_is_marked_offline() -> None:
    _reset_cluster()
    worker_id = _register("flaky-node", ["image"])

    stale = registry.get(worker_id)
    assert stale is not None
    repository.upsert_worker(
        stale.model_copy(update={"last_heartbeat_at": datetime.now(UTC) - timedelta(hours=1)})
    )

    offline = heartbeats.detect_timeouts()
    assert worker_id in {w.id for w in offline}
    assert registry.get(worker_id).status is WorkerState.OFFLINE  # type: ignore[union-attr]


def test_heartbeat_revives_an_offline_worker() -> None:
    _reset_cluster()
    worker_id = _register("returning-node", ["image"])
    registry.mark_offline(worker_id)

    revived = client.post("/workers/heartbeat", json={"worker_id": worker_id})
    assert revived.json()["status"] == "online"


def test_heartbeat_does_not_override_operator_state() -> None:
    """A paused worker must stay paused even though it keeps reporting in."""
    _reset_cluster()
    worker_id = _register("paused-node", ["image"])
    registry.pause(worker_id)

    still_paused = client.post("/workers/heartbeat", json={"worker_id": worker_id})
    assert still_paused.json()["status"] == "paused"


def test_heartbeat_for_unknown_worker_is_404() -> None:
    assert client.post("/workers/heartbeat", json={"worker_id": "nope"}).status_code == 404


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def test_dispatcher_matches_capability() -> None:
    _reset_cluster()
    registry.pause(LOCAL_WORKER_ID)
    image_worker = _register("image-node", ["image"])
    _register("audio-node", ["audio"])

    candidates = dispatcher.select_candidates("image")
    assert [c.worker.id for c in candidates] == [image_worker]
    registry.resume(LOCAL_WORKER_ID)


def test_dispatcher_prefers_least_loaded_worker() -> None:
    _reset_cluster()
    registry.pause(LOCAL_WORKER_ID)
    busy = _register("busy-node", ["image"], max_concurrency=4)
    idle = _register("idle-node", ["image"], max_concurrency=4)
    registry.adjust_load(busy, +3)

    candidates = dispatcher.select_candidates("image")
    assert candidates[0].worker.id == idle
    registry.resume(LOCAL_WORKER_ID)


def test_dispatcher_respects_affinity() -> None:
    _reset_cluster()
    registry.pause(LOCAL_WORKER_ID)
    _register("generic-node", ["image"])
    office = _register("office-node", ["image"], tags=["office"])

    candidates = dispatcher.select_candidates("image", affinity=["office"])
    assert [c.worker.id for c in candidates] == [office]
    registry.resume(LOCAL_WORKER_ID)


def test_dispatcher_skips_unavailable_workers() -> None:
    _reset_cluster()
    registry.pause(LOCAL_WORKER_ID)
    paused = _register("paused-node", ["image"])
    draining = _register("draining-node", ["image"])
    offline = _register("offline-node", ["image"])
    full = _register("full-node", ["image"], max_concurrency=1)

    registry.pause(paused)
    registry.drain(draining)
    registry.mark_offline(offline)
    registry.adjust_load(full, +1)

    assert dispatcher.select_candidates("image") == []
    registry.resume(LOCAL_WORKER_ID)


def test_draining_worker_keeps_work_but_takes_none() -> None:
    _reset_cluster()
    registry.pause(LOCAL_WORKER_ID)
    worker_id = _register("draining-node", ["image"])
    registry.adjust_load(worker_id, +1)
    registry.drain(worker_id)

    worker = registry.get(worker_id)
    assert worker is not None
    assert worker.current_load == 1, "running work is retained"
    assert dispatcher.select_candidates("image") == [], "but no new work is accepted"
    registry.resume(LOCAL_WORKER_ID)


def test_dispatcher_selection_is_deterministic() -> None:
    _reset_cluster()
    registry.pause(LOCAL_WORKER_ID)
    _register("node-b", ["image"], max_concurrency=2)
    _register("node-a", ["image"], max_concurrency=2)

    first = [c.worker.id for c in dispatcher.select_candidates("image")]
    second = [c.worker.id for c in dispatcher.select_candidates("image")]
    assert first == second
    registry.resume(LOCAL_WORKER_ID)


def test_unknown_capability_imposes_no_placement_constraint() -> None:
    """Routing is a hint. Work the provider layer would reject must still reach
    the provider layer instead of stalling on a machine that cannot exist."""
    _reset_cluster()
    entry_capability = "totally-unknown-capability"
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id = _schedule(agent_id, capability=entry_capability)

    schedule = repository.get_schedule(schedule_id)
    assert schedule is not None
    assert dispatcher._required_capability(schedule.queue_entries[0]) == ""


# ---------------------------------------------------------------------------
# Reservations and leases
# ---------------------------------------------------------------------------


def test_reservation_and_lease_lifecycle() -> None:
    _reset_cluster()
    worker_id = _register("lease-node", ["image"])

    reservation = leases.reserve(
        worker_id=worker_id, schedule_id="sched-1", entry_id="entry-1", capability="image"
    )
    assert reservation.state is ReservationState.ACTIVE

    lease = leases.acquire(
        reservation_id=reservation.id, worker_id=worker_id, execution_id=f"exec-1-{uuid4().hex[:8]}"
    )
    assert lease.is_active
    assert lease.expires_at > lease.created_at

    renewed = leases.renew(lease.id)
    assert renewed.renewed_at is not None
    assert renewed.expires_at > lease.expires_at

    assert leases.release(lease.id).state is LeaseState.RELEASED
    assert leases.release_reservation(reservation.id).state is ReservationState.RELEASED


def test_expired_lease_is_reclaimed() -> None:
    _reset_cluster()
    worker_id = _register("expiring-node", ["image"])
    reservation = leases.reserve(
        worker_id=worker_id, schedule_id="s", entry_id="e", capability="image"
    )
    lease = leases.acquire(
        reservation_id=reservation.id,
        worker_id=worker_id,
        execution_id=f"exec-x-{uuid4().hex[:8]}",
        lease_seconds=1,
    )

    stored = repository.get_lease(lease.id)
    assert stored is not None
    repository.update_lease(
        stored.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=5)})
    )

    expired = leases.expire_due()
    assert lease.id in {item.id for item in expired}
    assert leases.get_lease(lease.id).state is LeaseState.EXPIRED  # type: ignore[union-attr]


def test_renewing_a_dead_lease_raises() -> None:
    _reset_cluster()
    worker_id = _register("dead-lease-node", ["image"])
    reservation = leases.reserve(worker_id=worker_id, schedule_id="s", entry_id="e")
    lease = leases.acquire(
        reservation_id=reservation.id, worker_id=worker_id, execution_id=f"exec-y-{uuid4().hex[:8]}"
    )
    leases.expire(lease.id)

    with pytest.raises(LeaseManagerError, match="cannot be renewed"):
        leases.renew(lease.id)


def test_releasing_twice_is_safe() -> None:
    _reset_cluster()
    worker_id = _register("idempotent-node", ["image"])
    reservation = leases.reserve(worker_id=worker_id, schedule_id="s", entry_id="e")
    lease = leases.acquire(
        reservation_id=reservation.id, worker_id=worker_id, execution_id=f"exec-z-{uuid4().hex[:8]}"
    )

    leases.release(lease.id)
    assert leases.release(lease.id).state is LeaseState.RELEASED
    leases.release_reservation(reservation.id)
    assert leases.release_reservation(reservation.id).state is ReservationState.RELEASED


def test_reservation_events_are_emitted() -> None:
    from atlas_kernel.api import event_bus

    seen: list[str] = []
    for event_type in (ReservationCreated, ExecutionAssigned, LeaseExpired):
        event_bus.subscribe(event_type, lambda e: seen.append(type(e).__name__))

    _reset_cluster()
    worker_id = _register("event-node", ["image"])
    reservation = leases.reserve(worker_id=worker_id, schedule_id="s", entry_id="e")
    lease = leases.acquire(
        reservation_id=reservation.id, worker_id=worker_id, execution_id=f"exec-e-{uuid4().hex[:8]}"
    )
    leases.expire(lease.id)

    assert "ReservationCreated" in seen
    assert "LeaseExpired" in seen


# ---------------------------------------------------------------------------
# Runtime placement
# ---------------------------------------------------------------------------


def test_execution_is_assigned_a_worker_lease_and_reservation() -> None:
    _reset_cluster()
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id = _schedule(agent_id)

    execution = runtime.agent_runtime.start_schedule(schedule_id)[0]

    assert execution.status is RuntimeExecutionStatus.COMPLETED
    assert execution.worker_id == LOCAL_WORKER_ID
    assert execution.placement_reason
    stored = repository.get_runtime_execution(execution.execution_id)
    assert stored is not None
    assert stored.worker_id == LOCAL_WORKER_ID


def test_completed_execution_releases_the_worker_slot() -> None:
    """A leaked lease would permanently shrink cluster capacity."""
    _reset_cluster()
    before = registry.get(LOCAL_WORKER_ID)
    assert before is not None

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    runtime.agent_runtime.start_schedule(_schedule(agent_id))

    after = registry.get(LOCAL_WORKER_ID)
    assert after is not None
    assert after.current_load == before.current_load, "slot must be returned"
    assert not leases.list_active_leases(LOCAL_WORKER_ID), "no lease may outlive its execution"


def test_execution_waits_when_no_worker_can_take_it() -> None:
    _reset_cluster()
    registry.pause(LOCAL_WORKER_ID)

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    jobs_before = len(repository.list_jobs())

    execution = runtime.agent_runtime.start_schedule(_schedule(agent_id))[0]

    assert execution.status is RuntimeExecutionStatus.WAITING_PLACEMENT
    assert execution.job_id is None, "no work may be created before placement"
    assert execution.provider_name is None
    assert len(repository.list_jobs()) == jobs_before
    assert "no worker is online" in (execution.placement_reason or "")

    schedule = repository.get_schedule(execution.schedule_id)
    assert schedule is not None
    assert schedule.queue_entries[0].status is QueueEntryStatus.WAITING_PLACEMENT

    registry.resume(LOCAL_WORKER_ID)


def test_waiting_execution_runs_once_a_worker_appears() -> None:
    _reset_cluster()
    registry.pause(LOCAL_WORKER_ID)

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    execution = runtime.agent_runtime.start_schedule(_schedule(agent_id))[0]
    assert execution.status is RuntimeExecutionStatus.WAITING_PLACEMENT

    registry.resume(LOCAL_WORKER_ID)
    resumed = runtime.agent_runtime.resume_after_placement(execution.execution_id)

    assert resumed.execution_id == execution.execution_id
    assert resumed.status is RuntimeExecutionStatus.COMPLETED
    assert resumed.worker_id == LOCAL_WORKER_ID


def test_waiting_placement_is_distinct_from_waiting_approval() -> None:
    assert QueueEntryStatus.WAITING_PLACEMENT != QueueEntryStatus.WAITING_APPROVAL
    assert QueueEntryStatus.WAITING_PLACEMENT != QueueEntryStatus.READY
    assert RuntimeExecutionStatus.WAITING_PLACEMENT != RuntimeExecutionStatus.WAITING_APPROVAL


def test_affinity_routes_execution_to_the_tagged_worker() -> None:
    _reset_cluster()
    registry.pause(LOCAL_WORKER_ID)
    _register("generic", ["image"])
    office = _register("office-a6000", ["image"], tags=["office"])

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id = _schedule(agent_id, payload={"worker_affinity": ["office"]})

    execution = runtime.agent_runtime.start_schedule(schedule_id)[0]
    assert execution.worker_id == office
    registry.resume(LOCAL_WORKER_ID)


# ---------------------------------------------------------------------------
# Failure recovery
# ---------------------------------------------------------------------------


def test_recover_execution_requeues_and_frees_the_slot() -> None:
    _reset_cluster()
    worker_id = _register("crashing-node", ["image"], max_concurrency=2)
    registry.pause(LOCAL_WORKER_ID)

    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id = _schedule(agent_id)

    # Place, then simulate the worker dying mid-flight.
    schedule = repository.get_schedule(schedule_id)
    assert schedule is not None
    entry = schedule.queue_entries[0]
    execution_id = f"exec-crash-{uuid4().hex[:8]}"
    verdict = dispatcher.place(schedule, entry, execution_id)
    assert verdict.placed

    from atlas_kernel.agents.schedule_models import RuntimeExecutionRecord

    execution = RuntimeExecutionRecord(
        execution_id=execution_id,
        schedule_id=schedule_id,
        entry_id=entry.id,
        agent_id=agent_id,
        plan_id=schedule.plan_id,
        action="image.generate",
        status=RuntimeExecutionStatus.RUNNING,
        worker_id=verdict.worker_id,
        lease_id=verdict.lease_id,
        reservation_id=verdict.reservation_id,
    )
    repository.create_runtime_execution(execution)

    recovered = runtime.agent_runtime.recover_execution(execution_id, reason="worker crash")

    assert recovered.status is RuntimeExecutionStatus.QUEUED
    assert recovered.worker_id is None
    assert leases.get_lease(verdict.lease_id or "").state is LeaseState.EXPIRED  # type: ignore[union-attr]

    worker = registry.get(worker_id)
    assert worker is not None
    assert worker.current_load == 0, "the dead worker's slot must be returned"

    schedule_after = repository.get_schedule(schedule_id)
    assert schedule_after is not None
    assert schedule_after.queue_entries[0].status is QueueEntryStatus.READY
    assert schedule_after.queue_entries[0].retry_count == 1

    registry.resume(LOCAL_WORKER_ID)


def test_recovery_emits_event() -> None:
    from atlas_kernel.api import event_bus

    seen: list[ExecutionRecovered] = []
    event_bus.subscribe(ExecutionRecovered, seen.append)

    _reset_cluster()
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    execution = runtime.agent_runtime.start_schedule(_schedule(agent_id))[0]

    runtime.agent_runtime.recover_execution(execution.execution_id, reason="manual")
    assert seen
    assert seen[-1].reason == "manual"


def test_cluster_sweep_recovers_stranded_work() -> None:
    _reset_cluster()
    project_id = _create_project()
    agent_id = _create_agent(project_id)
    schedule_id = _schedule(agent_id)

    schedule = repository.get_schedule(schedule_id)
    assert schedule is not None
    entry = schedule.queue_entries[0]
    execution_id = f"exec-stranded-{uuid4().hex[:8]}"
    verdict = dispatcher.place(schedule, entry, execution_id)

    from atlas_kernel.agents.schedule_models import RuntimeExecutionRecord

    repository.create_runtime_execution(
        RuntimeExecutionRecord(
            execution_id=execution_id,
            schedule_id=schedule_id,
            entry_id=entry.id,
            agent_id=agent_id,
            plan_id=schedule.plan_id,
            action="image.generate",
            status=RuntimeExecutionStatus.RUNNING,
            worker_id=verdict.worker_id,
            lease_id=verdict.lease_id,
            reservation_id=verdict.reservation_id,
        )
    )
    stored_lease = repository.get_lease(verdict.lease_id or "")
    assert stored_lease is not None
    repository.update_lease(
        stored_lease.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=10)})
    )

    result = client.post("/cluster/sweep").json()
    assert verdict.lease_id in result["leases_expired"]
    assert execution_id in result["executions_recovered"]


# ---------------------------------------------------------------------------
# Cluster state + API
# ---------------------------------------------------------------------------


def test_cluster_health_and_load() -> None:
    _reset_cluster()
    _register("health-node", ["image"], max_concurrency=2)

    health = client.get("/cluster/health").json()
    assert health["total_workers"] >= 2
    assert health["online"] >= 1

    load = client.get("/cluster/load").json()
    assert load["total_capacity"] >= 2
    assert any(w["worker_id"] == LOCAL_WORKER_ID for w in load["per_worker"])


def test_cluster_health_reports_stale_heartbeats() -> None:
    _reset_cluster()
    worker_id = _register("stale-node", ["image"])
    stale = registry.get(worker_id)
    assert stale is not None
    repository.upsert_worker(
        stale.model_copy(update={"last_heartbeat_at": datetime.now(UTC) - timedelta(hours=2)})
    )

    health = cluster_state.health()
    assert worker_id in health.stale_heartbeats
    assert health.healthy is False


def test_cluster_snapshot_endpoint() -> None:
    _reset_cluster()
    snapshot = client.get("/cluster").json()
    assert "health" in snapshot
    assert "load" in snapshot
    assert any(w["id"] == LOCAL_WORKER_ID for w in snapshot["workers"])


def test_worker_api_round_trip() -> None:
    _reset_cluster()
    registered = client.post(
        "/workers/register",
        json={
            "hostname": "api-node",
            "display_name": "API Node",
            "capabilities": ["image", "video"],
            "max_concurrency": 3,
            "tags": ["remote"],
            "resources": {"cpu_cores": 16, "ram_gb": 64, "gpu": "4090", "vram_gb": 24},
        },
    )
    assert registered.status_code == 200
    worker_id = registered.json()["id"]

    assert worker_id in {w["id"] for w in client.get("/workers").json()}

    detail = client.get(f"/workers/{worker_id}").json()
    assert detail["display_name"] == "API Node"
    assert "reservations" in detail and "leases" in detail and "heartbeats" in detail

    assert client.post(f"/workers/{worker_id}/pause").json()["status"] == "paused"
    assert client.post(f"/workers/{worker_id}/resume").json()["status"] == "online"
    assert client.post(f"/workers/{worker_id}/drain").json()["status"] == "draining"


def test_worker_api_404s() -> None:
    assert client.get("/workers/missing-worker").status_code == 404
    assert client.post("/workers/missing-worker/pause").status_code == 404


def test_workers_can_be_filtered_by_status() -> None:
    _reset_cluster()
    worker_id = _register("filterable", ["image"])
    registry.pause(worker_id)

    paused = client.get("/workers", params={"status": "paused"}).json()
    assert worker_id in {w["id"] for w in paused}
    assert LOCAL_WORKER_ID not in {w["id"] for w in paused}


# ---------------------------------------------------------------------------
# Architecture contracts
# ---------------------------------------------------------------------------


def test_cluster_layer_never_touches_providers() -> None:
    for name in ("dispatcher.py", "worker_registry.py", "lease_manager.py", "heartbeat_service.py"):
        source = (KERNEL_ROOT / "cluster" / name).read_text(encoding="utf-8")
        assert "ProviderManager" not in source
        assert "ProviderRouter" not in source
        assert "select_provider(" not in source
        assert "from ..providers" not in source


def test_scheduler_and_providers_stay_unaware_of_workers() -> None:
    scheduler = (KERNEL_ROOT / "agents" / "scheduler.py").read_text(encoding="utf-8")
    providers = (KERNEL_ROOT / "providers.py").read_text(encoding="utf-8")

    assert "worker_id" not in scheduler, "scheduler must not be redesigned around workers"
    assert "cluster" not in scheduler.lower()
    assert "worker_id" not in providers, "providers never learn which machine ran them"


def test_no_forbidden_orchestration_dependencies() -> None:
    """Milestone 009 forbids Kubernetes, Ray, Celery and message brokers."""
    forbidden = ("kubernetes", "ray.", "celery", "kombu", "pika", "docker.from_env")
    for path in (KERNEL_ROOT / "cluster").glob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in source, f"{path.name} references {token}"


def test_runtime_placement_gate_is_optional() -> None:
    """A runtime built without a dispatcher behaves exactly as before M009."""
    from atlas_kernel.agents.runtime import AgentRuntime

    assert AgentRuntime().placement_gate is None


def test_every_agent_runtime_in_the_api_carries_the_placement_gate() -> None:
    from atlas_kernel.api import agent_foundation
    from atlas_kernel.api import runtime as composed

    assert composed.agent_runtime.placement_gate is not None
    assert agent_foundation._runtime.placement_gate is not None
    assert agent_foundation._runtime.placement_gate is composed.dispatcher


def test_cluster_services_constructed_only_in_composition_root() -> None:
    constructed = {"WorkerRegistry", "Dispatcher", "LeaseManager", "HeartbeatService"}
    for path in KERNEL_ROOT.glob("*.py"):
        if path.name in {"composition_root.py", "api.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in constructed
            ):
                raise AssertionError(
                    f"{path.name} constructs {node.func.id} outside composition root"
                )
