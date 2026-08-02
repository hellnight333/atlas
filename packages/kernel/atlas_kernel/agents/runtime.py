from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from ..cluster.events import ExecutionRecovered
from ..models import CapabilityRequest, Job, JobStatus, Run
from ..repository import AtlasRepository
from ..worker import Worker
from .events import (
    RuntimeCancelled,
    RuntimeCompleted,
    RuntimeFailed,
    RuntimePreparing,
    RuntimeProgress,
    RuntimeRunning,
    RuntimeStarted,
    RuntimeTimedOut,
)
from .models import ALLOWED_STATUS_TRANSITIONS, Agent, AgentStatus
from .schedule_models import (
    ExecutionSchedule,
    QueueEntryStatus,
    RuntimeExecutionRecord,
    RuntimeExecutionStatus,
    RuntimeRetryPolicy,
    ScheduleQueueEntry,
)


@dataclass
class RuntimeCancellationToken:
    cancelled: bool = False
    reason: str | None = None

    def cancel(self, reason: str = "cancelled") -> None:
        self.cancelled = True
        self.reason = reason


@dataclass(frozen=True)
class ApprovalVerdict:
    """What an approval gate tells the runtime to do with one entry."""

    allowed: bool
    approval_id: str | None = None
    reason: str = ""
    rejected: bool = False
    expired: bool = False


@dataclass(frozen=True)
class PlacementResult:
    """What a placement gate tells the runtime about where an entry may run."""

    placed: bool
    worker_id: str | None = None
    reservation_id: str | None = None
    lease_id: str | None = None
    reason: str = ""


class PlacementGate(Protocol):
    """Implemented by the cluster layer. Like ApprovalGate, the runtime knows
    only this shape, so the cluster domain stays outside its dependencies."""

    def place(
        self, schedule: ExecutionSchedule, entry: ScheduleQueueEntry, execution_id: str
    ) -> PlacementResult: ...

    def release(
        self,
        *,
        worker_id: str | None,
        reservation_id: str | None,
        lease_id: str | None,
        reason: str = "completed",
        expired: bool = False,
    ) -> None: ...


class ApprovalGate(Protocol):
    """Implemented by the approval layer. The runtime knows only this shape, so
    the approval domain stays outside the runtime's dependencies."""

    def check(
        self, schedule: ExecutionSchedule, entry: ScheduleQueueEntry, execution_id: str
    ) -> ApprovalVerdict: ...


class AgentRuntime:
    def __init__(self, repository: AtlasRepository | None = None, event_bus: object | None = None, worker: Worker | None = None, max_gpu_jobs: int = 1, max_cpu_jobs: int = 4, max_provider_jobs: int = 4, approval_gate: ApprovalGate | None = None, placement_gate: PlacementGate | None = None) -> None:
        self.repository = repository
        self.event_bus = event_bus
        self.worker = worker
        self.max_gpu_jobs = max_gpu_jobs
        self.max_cpu_jobs = max_cpu_jobs
        self.max_provider_jobs = max_provider_jobs
        self.approval_gate = approval_gate
        self.placement_gate = placement_gate

    @staticmethod
    def transition(agent: Agent, next_status: AgentStatus) -> Agent:
        current = agent.status
        if current == next_status:
            return agent
        allowed = ALLOWED_STATUS_TRANSITIONS.get(current, set())
        if next_status not in allowed:
            raise ValueError(
                f"Invalid agent status transition: {current.value} -> {next_status.value}"
            )
        return agent.model_copy(update={"status": next_status})

    def start_schedule(
        self,
        schedule_id: str,
        retry_policy: RuntimeRetryPolicy | None = None,
        timeout_seconds: float = 30.0,
        heartbeat_interval_seconds: float = 0.05,
    ) -> list[RuntimeExecutionRecord]:
        if self.repository is None or self.event_bus is None or self.worker is None:
            raise ValueError("Runtime is not configured for execution")

        schedule = self.repository.get_schedule(schedule_id)
        if schedule is None:
            raise ValueError("Schedule not found")

        executions: list[RuntimeExecutionRecord] = []
        for entry in schedule.queue_entries:
            if entry.status != QueueEntryStatus.READY:
                continue
            executions.append(
                self.execute_entry(
                    schedule,
                    entry,
                    retry_policy=retry_policy or RuntimeRetryPolicy(),
                    timeout_seconds=timeout_seconds,
                    heartbeat_interval_seconds=heartbeat_interval_seconds,
                )
            )
        return executions

    def execute_entry(
        self,
        schedule: ExecutionSchedule,
        entry: ScheduleQueueEntry,
        *,
        retry_policy: RuntimeRetryPolicy,
        timeout_seconds: float,
        heartbeat_interval_seconds: float,
        execution: RuntimeExecutionRecord | None = None,
    ) -> RuntimeExecutionRecord:
        if execution is None:
            execution = RuntimeExecutionRecord(
                schedule_id=schedule.schedule_id,
                entry_id=entry.id,
                agent_id=schedule.agent_id,
                plan_id=schedule.plan_id,
                action=entry.plan_step.action,
                payload=dict(entry.plan_step.payload),
                status=RuntimeExecutionStatus.QUEUED,
                retry_policy=retry_policy,
            )
            execution.timeline.append({"status": execution.status.value, "timestamp": execution.created_at.isoformat()})
            self.repository.create_runtime_execution(execution)
        else:
            # Resuming a paused execution: keep the same record so the approval
            # that gated it still points at a live execution.
            execution.status = RuntimeExecutionStatus.QUEUED
            execution.retry_policy = retry_policy
            execution.attempts = 0
            execution.error = None
            execution.updated_at = datetime.now(UTC)
            execution.timeline.append({"status": execution.status.value, "timestamp": execution.updated_at.isoformat(), "resumed": True})
            self.repository.update_runtime_execution(execution)
        self.event_bus.publish(RuntimeStarted(execution_id=execution.execution_id, schedule_id=execution.schedule_id, entry_id=execution.entry_id))

        # Approval gate. Nothing below this point may run without a verdict:
        # no job is created, no provider is reached, no state is mutated.
        gated = self._apply_approval_gate(schedule, entry, execution)
        if gated is not None:
            return gated

        # Placement. Work is only ever created once a worker slot is reserved
        # and a lease is held, so nothing runs on a machine that never agreed.
        unplaced = self._apply_placement_gate(schedule, entry, execution)
        if unplaced is not None:
            return unplaced

        token = RuntimeCancellationToken()
        if entry.status == QueueEntryStatus.CANCELLED:
            token.cancel("cancelled before execution")

        delay = retry_policy.retry_delay
        while execution.attempts < retry_policy.max_attempts:
            execution.attempts += 1
            if token.cancelled:
                return self._mark_cancelled(schedule, entry, execution, token.reason or "cancelled")

            now = datetime.now(UTC)
            execution.status = RuntimeExecutionStatus.PREPARING
            execution.started_at = execution.started_at or now
            execution.heartbeat_at = now
            execution.deadline_at = now + timedelta(seconds=timeout_seconds)
            execution.updated_at = now
            execution.timeline.append({"status": execution.status.value, "timestamp": now.isoformat(), "attempt": execution.attempts})
            self.repository.update_runtime_execution(execution)
            entry.status = QueueEntryStatus.PREPARING
            entry.started_time = now
            self.repository.update_schedule(schedule)
            self.event_bus.publish(RuntimePreparing(execution_id=execution.execution_id, schedule_id=execution.schedule_id, entry_id=execution.entry_id))

            job = self._create_job(schedule, entry)
            execution.run_id = job.run_id
            execution.job_id = job.id

            execution.status = RuntimeExecutionStatus.RUNNING
            execution.updated_at = datetime.now(UTC)
            execution.timeline.append({"status": execution.status.value, "timestamp": execution.updated_at.isoformat(), "attempt": execution.attempts})
            self.repository.update_runtime_execution(execution)
            entry.status = QueueEntryStatus.RUNNING
            self.repository.update_schedule(schedule)
            self.event_bus.publish(RuntimeRunning(execution_id=execution.execution_id, schedule_id=execution.schedule_id, entry_id=execution.entry_id))

            pool = ThreadPoolExecutor(max_workers=1)
            future = pool.submit(self.worker.execute, job, token)
            timed_out = False
            result: dict[str, object] | None = None
            try:
                while True:
                    if future.done():
                        result = future.result()
                        break
                    now = datetime.now(UTC)
                    execution.heartbeat_at = now
                    execution.updated_at = now
                    self.repository.update_runtime_execution(execution)
                    self.event_bus.publish(
                        RuntimeProgress(
                            execution_id=execution.execution_id,
                            schedule_id=execution.schedule_id,
                            entry_id=execution.entry_id,
                            heartbeat_at=now.isoformat(),
                        )
                    )
                    if execution.deadline_at is not None and now >= execution.deadline_at:
                        token.cancel("deadline exceeded")
                        timed_out = True
                        break
                    time.sleep(heartbeat_interval_seconds)
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            if timed_out:
                return self._mark_timed_out(schedule, entry, execution, "deadline exceeded")

            assert result is not None
            execution.provider_name = result.get("provider") if isinstance(result.get("provider"), str) else None
            execution.output = result.get("output") if isinstance(result.get("output"), dict) else {}
            execution.asset_id = result.get("asset_id") if isinstance(result.get("asset_id"), str) else None
            execution.error = result.get("error") if isinstance(result.get("error"), str) else None

            if token.cancelled or result.get("status") == JobStatus.CANCELLED.value:
                return self._mark_cancelled(schedule, entry, execution, token.reason or "cancelled")

            if result.get("status") == JobStatus.COMPLETED.value:
                return self._mark_completed(schedule, entry, execution)

            if self._is_transient_failure(execution.error) and execution.attempts < retry_policy.max_attempts:
                time.sleep(delay)
                delay = delay * retry_policy.backoff if delay > 0 else 0.0
                continue
            return self._mark_failed(schedule, entry, execution, execution.error or "execution failed")

        return self._mark_failed(schedule, entry, execution, execution.error or "execution failed")

    def _apply_approval_gate(
        self,
        schedule: ExecutionSchedule,
        entry: ScheduleQueueEntry,
        execution: RuntimeExecutionRecord,
    ) -> RuntimeExecutionRecord | None:
        """Returns a terminal/paused execution when the gate withholds consent,
        or None when execution may proceed."""
        if self.approval_gate is None:
            return None

        verdict = self.approval_gate.check(schedule, entry, execution.execution_id)
        if verdict.allowed:
            if verdict.approval_id:
                execution.approval_id = verdict.approval_id
                self.repository.update_runtime_execution(execution)
            return None

        now = datetime.now(UTC)
        execution.approval_id = verdict.approval_id
        execution.updated_at = now

        if verdict.rejected or verdict.expired:
            execution.status = RuntimeExecutionStatus.APPROVAL_REJECTED
            execution.completed_at = now
            execution.error = verdict.reason or (
                "approval expired" if verdict.expired else "approval rejected"
            )
            entry.status = QueueEntryStatus.CANCELLED
            entry.completed_time = now
        else:
            execution.status = RuntimeExecutionStatus.WAITING_APPROVAL
            entry.status = QueueEntryStatus.WAITING_APPROVAL

        execution.timeline.append(
            {
                "status": execution.status.value,
                "timestamp": now.isoformat(),
                "approval_id": verdict.approval_id,
                "reason": verdict.reason,
            }
        )
        self.repository.update_runtime_execution(execution)
        self.repository.update_schedule(schedule)
        return execution

    def _apply_placement_gate(
        self,
        schedule: ExecutionSchedule,
        entry: ScheduleQueueEntry,
        execution: RuntimeExecutionRecord,
    ) -> RuntimeExecutionRecord | None:
        """Returns a paused execution when no worker can take the entry, or
        None once a reservation and lease are held."""
        if self.placement_gate is None:
            return None

        result = self.placement_gate.place(schedule, entry, execution.execution_id)
        now = datetime.now(UTC)

        if result.placed:
            execution.worker_id = result.worker_id
            execution.reservation_id = result.reservation_id
            execution.lease_id = result.lease_id
            execution.placement_reason = result.reason
            execution.updated_at = now
            execution.timeline.append(
                {
                    "status": "assigned",
                    "timestamp": now.isoformat(),
                    "worker_id": result.worker_id,
                    "lease_id": result.lease_id,
                }
            )
            self.repository.update_runtime_execution(execution)
            return None

        execution.status = RuntimeExecutionStatus.WAITING_PLACEMENT
        execution.placement_reason = result.reason
        execution.updated_at = now
        execution.timeline.append(
            {
                "status": execution.status.value,
                "timestamp": now.isoformat(),
                "reason": result.reason,
            }
        )
        self.repository.update_runtime_execution(execution)
        entry.status = QueueEntryStatus.WAITING_PLACEMENT
        self.repository.update_schedule(schedule)
        return execution

    def _release_placement(
        self, execution: RuntimeExecutionRecord, reason: str, expired: bool = False
    ) -> None:
        """Every terminal path releases the worker slot. A leaked lease would
        permanently shrink cluster capacity."""
        if self.placement_gate is None or execution.lease_id is None:
            return
        self.placement_gate.release(
            worker_id=execution.worker_id,
            reservation_id=execution.reservation_id,
            lease_id=execution.lease_id,
            reason=reason,
            expired=expired,
        )
        execution.lease_id = None
        execution.reservation_id = None

    def resume_after_placement(
        self,
        execution_id: str,
        *,
        retry_policy: RuntimeRetryPolicy | None = None,
        timeout_seconds: float = 30.0,
        heartbeat_interval_seconds: float = 0.05,
    ) -> RuntimeExecutionRecord:
        """Retries placement for an execution that had nowhere to run."""
        if self.repository is None or self.event_bus is None or self.worker is None:
            raise ValueError("Runtime is not configured for execution")

        execution = self.repository.get_runtime_execution(execution_id)
        if execution is None:
            raise ValueError("Runtime execution not found")
        if execution.status is not RuntimeExecutionStatus.WAITING_PLACEMENT:
            raise ValueError(
                f"Execution {execution_id} is {execution.status.value}, not waiting for placement"
            )

        schedule = self.repository.get_schedule(execution.schedule_id)
        if schedule is None:
            raise ValueError("Schedule not found")
        entry = next((e for e in schedule.queue_entries if e.id == execution.entry_id), None)
        if entry is None:
            raise ValueError("Queue entry not found")

        entry.status = QueueEntryStatus.READY
        self.repository.update_schedule(schedule)
        return self.execute_entry(
            schedule,
            entry,
            retry_policy=retry_policy or execution.retry_policy,
            timeout_seconds=timeout_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            execution=execution,
        )

    def recover_execution(
        self, execution_id: str, reason: str = "worker failure"
    ) -> RuntimeExecutionRecord:
        """Requeues an execution stranded by a dead worker or an expired lease.

        The lease is expired rather than released, the worker slot is returned,
        and the entry goes back to READY so the dispatcher can place it
        elsewhere on the next attempt.
        """
        if self.repository is None:
            raise ValueError("Runtime is not configured for execution")

        execution = self.repository.get_runtime_execution(execution_id)
        if execution is None:
            raise ValueError("Runtime execution not found")

        self._release_placement(execution, reason=reason, expired=True)

        now = datetime.now(UTC)
        previous_worker = execution.worker_id
        execution.status = RuntimeExecutionStatus.QUEUED
        execution.worker_id = None
        execution.placement_reason = reason
        execution.error = None
        execution.updated_at = now
        execution.timeline.append(
            {
                "status": "recovered",
                "timestamp": now.isoformat(),
                "reason": reason,
                "previous_worker_id": previous_worker,
            }
        )
        self.repository.update_runtime_execution(execution)

        schedule = self.repository.get_schedule(execution.schedule_id)
        if schedule is not None:
            for entry in schedule.queue_entries:
                if entry.id == execution.entry_id:
                    entry.status = QueueEntryStatus.READY
                    entry.retry_count += 1
                    entry.started_time = None
                    break
            self.repository.update_schedule(schedule)

        if self.event_bus is not None:
            self.event_bus.publish(
                ExecutionRecovered(
                    execution_id=execution_id,
                    worker_id=previous_worker or "",
                    reason=reason,
                )
            )
        return execution

    def list_waiting_placement(self) -> list[RuntimeExecutionRecord]:
        if self.repository is None:
            return []
        return [
            execution
            for execution in self.repository.list_runtime_executions()
            if execution.status is RuntimeExecutionStatus.WAITING_PLACEMENT
        ]

    def resume_after_approval(
        self,
        execution_id: str,
        *,
        retry_policy: RuntimeRetryPolicy | None = None,
        timeout_seconds: float = 30.0,
        heartbeat_interval_seconds: float = 0.05,
    ) -> RuntimeExecutionRecord:
        """Re-runs an execution that was paused awaiting approval. The gate is
        consulted again, so a still-pending approval simply pauses once more."""
        if self.repository is None or self.event_bus is None or self.worker is None:
            raise ValueError("Runtime is not configured for execution")

        execution = self.repository.get_runtime_execution(execution_id)
        if execution is None:
            raise ValueError("Runtime execution not found")
        if execution.status is not RuntimeExecutionStatus.WAITING_APPROVAL:
            raise ValueError(
                f"Execution {execution_id} is {execution.status.value}, not waiting for approval"
            )

        schedule = self.repository.get_schedule(execution.schedule_id)
        if schedule is None:
            raise ValueError("Schedule not found")
        entry = next((e for e in schedule.queue_entries if e.id == execution.entry_id), None)
        if entry is None:
            raise ValueError("Queue entry not found")

        entry.status = QueueEntryStatus.READY
        self.repository.update_schedule(schedule)

        return self.execute_entry(
            schedule,
            entry,
            retry_policy=retry_policy or execution.retry_policy,
            timeout_seconds=timeout_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            execution=execution,
        )

    def list_waiting_approval(self) -> list[RuntimeExecutionRecord]:
        if self.repository is None:
            return []
        return [
            execution
            for execution in self.repository.list_runtime_executions()
            if execution.status is RuntimeExecutionStatus.WAITING_APPROVAL
        ]

    def list_runtime_executions(self) -> list[RuntimeExecutionRecord]:
        if self.repository is None:
            return []
        return self.repository.list_runtime_executions()

    def list_running(self) -> list[RuntimeExecutionRecord]:
        if self.repository is None:
            return []
        return self.repository.list_running_runtime_executions()

    def list_history(self) -> list[RuntimeExecutionRecord]:
        if self.repository is None:
            return []
        return self.repository.list_runtime_history()

    def get_runtime_execution(self, execution_id: str) -> RuntimeExecutionRecord | None:
        if self.repository is None:
            return None
        return self.repository.get_runtime_execution(execution_id)

    def cancel_execution(self, execution_id: str) -> RuntimeExecutionRecord:
        if self.repository is None:
            raise ValueError("Runtime is not configured for execution")
        execution = self.repository.get_runtime_execution(execution_id)
        if execution is None:
            raise ValueError("Runtime execution not found")
        execution.cancellation_requested = True
        execution.updated_at = datetime.now(UTC)
        if execution.status in {RuntimeExecutionStatus.PENDING, RuntimeExecutionStatus.QUEUED, RuntimeExecutionStatus.PREPARING}:
            self._release_placement(execution, reason="cancelled", expired=False)
            execution.status = RuntimeExecutionStatus.CANCELLED
            execution.completed_at = execution.updated_at
        self.repository.update_runtime_execution(execution)
        return execution

    def retry_execution(self, execution_id: str, timeout_seconds: float = 30.0, heartbeat_interval_seconds: float = 0.05) -> RuntimeExecutionRecord:
        if self.repository is None:
            raise ValueError("Runtime is not configured for execution")
        existing = self.repository.get_runtime_execution(execution_id)
        if existing is None:
            raise ValueError("Runtime execution not found")
        schedule = self.repository.get_schedule(existing.schedule_id)
        if schedule is None:
            raise ValueError("Schedule not found")
        entry = next((item for item in schedule.queue_entries if item.id == existing.entry_id), None)
        if entry is None:
            raise ValueError("Schedule entry not found")
        entry.status = QueueEntryStatus.READY
        self.repository.update_schedule(schedule)
        return self.execute_entry(
            schedule,
            entry,
            retry_policy=existing.retry_policy,
            timeout_seconds=timeout_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        )

    def _create_job(self, schedule: ExecutionSchedule, entry: ScheduleQueueEntry) -> Job:
        now = datetime.now(UTC)
        run = Run(
            id=f"run-{uuid4().hex[:8]}",
            title=entry.plan_step.description,
            description=entry.plan_step.description,
            studio=self._studio_for_action(entry.plan_step.action),
            project_id=self._project_id_for_schedule(schedule),
            status=JobStatus.QUEUED,
            created_at=now,
        )
        self.repository.create_run(run)
        job = Job(
            id=f"job-{uuid4().hex[:8]}",
            run_id=run.id,
            action=entry.plan_step.action,
            payload=dict(entry.plan_step.payload),
            status=JobStatus.QUEUED,
            attempts=max(0, entry.retry_count),
            priority=0,
            capability_req=CapabilityRequest(
                capability_id=self._capability_id_for_entry(entry),
                requirements={},
            ),
            created_at=now,
        )
        self.repository.create_job(job)
        return job

    def _capability_id_for_entry(self, entry: ScheduleQueueEntry) -> str:
        capability = entry.capability.lower()
        action = entry.plan_step.action
        if capability.startswith("cap-"):
            return capability
        if action.startswith("image.") or "image" in capability or "media" in capability:
            return "cap-image-generation"
        if action.startswith("code.") or "code" in capability or "build" in capability:
            return "cap-code-generation"
        if capability in {"research", "workflow", "review", "planning", "reasoning", "text"}:
            return "cap-reasoning"
        if capability.replace("-", "_") in {"code_generation", "code", "build"}:
            return "cap-code-generation"
        if capability.replace("-", "_") in {"image_generation", "image", "media"}:
            return "cap-image-generation"
        return capability

    def _studio_for_action(self, action: str) -> str:
        if action.startswith("image."):
            return "image"
        if action.startswith("code."):
            return "code"
        return "text"

    def _project_id_for_schedule(self, schedule: ExecutionSchedule) -> str | None:
        agent = self.repository.get_agent(schedule.agent_id) if self.repository is not None else None
        return agent.project_id if agent is not None else None

    def _mark_completed(self, schedule: ExecutionSchedule, entry: ScheduleQueueEntry, execution: RuntimeExecutionRecord) -> RuntimeExecutionRecord:
        now = datetime.now(UTC)
        self._release_placement(execution, reason="completed", expired=False)
        execution.status = RuntimeExecutionStatus.COMPLETED
        execution.completed_at = now
        execution.updated_at = now
        execution.timeline.append({"status": execution.status.value, "timestamp": now.isoformat()})
        self.repository.update_runtime_execution(execution)
        entry.status = QueueEntryStatus.COMPLETED
        entry.completed_time = now
        self._unblock_ready_entries(schedule)
        self.repository.update_schedule(schedule)
        self.event_bus.publish(RuntimeCompleted(execution_id=execution.execution_id, schedule_id=execution.schedule_id, entry_id=execution.entry_id, asset_id=execution.asset_id))
        return execution

    def _mark_failed(self, schedule: ExecutionSchedule, entry: ScheduleQueueEntry, execution: RuntimeExecutionRecord, reason: str) -> RuntimeExecutionRecord:
        now = datetime.now(UTC)
        self._release_placement(execution, reason="failed", expired=False)
        execution.status = RuntimeExecutionStatus.FAILED
        execution.error = reason
        execution.completed_at = now
        execution.updated_at = now
        execution.timeline.append({"status": execution.status.value, "timestamp": now.isoformat(), "reason": reason})
        self.repository.update_runtime_execution(execution)
        entry.status = QueueEntryStatus.FAILED
        entry.completed_time = now
        self.repository.update_schedule(schedule)
        self.event_bus.publish(RuntimeFailed(execution_id=execution.execution_id, schedule_id=execution.schedule_id, entry_id=execution.entry_id, reason=reason))
        return execution

    def _mark_cancelled(self, schedule: ExecutionSchedule, entry: ScheduleQueueEntry, execution: RuntimeExecutionRecord, reason: str) -> RuntimeExecutionRecord:
        now = datetime.now(UTC)
        self._release_placement(execution, reason="cancelled", expired=False)
        execution.status = RuntimeExecutionStatus.CANCELLED
        execution.error = reason
        execution.cancellation_requested = True
        execution.completed_at = now
        execution.updated_at = now
        execution.timeline.append({"status": execution.status.value, "timestamp": now.isoformat(), "reason": reason})
        self.repository.update_runtime_execution(execution)
        entry.status = QueueEntryStatus.CANCELLED
        entry.completed_time = now
        self.repository.update_schedule(schedule)
        self.event_bus.publish(RuntimeCancelled(execution_id=execution.execution_id, schedule_id=execution.schedule_id, entry_id=execution.entry_id))
        return execution

    def _mark_timed_out(self, schedule: ExecutionSchedule, entry: ScheduleQueueEntry, execution: RuntimeExecutionRecord, reason: str) -> RuntimeExecutionRecord:
        now = datetime.now(UTC)
        self._release_placement(execution, reason="timed out", expired=True)
        execution.status = RuntimeExecutionStatus.TIMED_OUT
        execution.timeout_reason = reason
        execution.completed_at = now
        execution.updated_at = now
        execution.timeline.append({"status": execution.status.value, "timestamp": now.isoformat(), "reason": reason})
        self.repository.update_runtime_execution(execution)
        entry.status = QueueEntryStatus.TIMED_OUT
        entry.completed_time = now
        self.repository.update_schedule(schedule)
        self.event_bus.publish(RuntimeTimedOut(execution_id=execution.execution_id, schedule_id=execution.schedule_id, entry_id=execution.entry_id, reason=reason))
        return execution

    def _unblock_ready_entries(self, schedule: ExecutionSchedule) -> None:
        completed_step_ids = {
            item.plan_step.id
            for item in schedule.queue_entries
            if item.status == QueueEntryStatus.COMPLETED
        }
        blocked_entries: list[str] = []
        for item in schedule.queue_entries:
            if item.status in {QueueEntryStatus.QUEUED, QueueEntryStatus.BLOCKED}:
                if all(dep in completed_step_ids for dep in item.dependencies):
                    item.status = QueueEntryStatus.READY
                elif item.dependencies:
                    item.status = QueueEntryStatus.BLOCKED
                    blocked_entries.append(item.id)
        schedule.blocked_entries = blocked_entries

    def _is_transient_failure(self, reason: str | None) -> bool:
        if not reason:
            return False
        normalized = reason.lower()
        return any(token in normalized for token in ["transient", "timeout", "temporary", "unavailable", "network", "retry"])
