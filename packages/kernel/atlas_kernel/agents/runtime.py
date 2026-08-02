from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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


class AgentRuntime:
    def __init__(self, repository: AtlasRepository | None = None, event_bus: object | None = None, worker: Worker | None = None, max_gpu_jobs: int = 1, max_cpu_jobs: int = 4, max_provider_jobs: int = 4) -> None:
        self.repository = repository
        self.event_bus = event_bus
        self.worker = worker
        self.max_gpu_jobs = max_gpu_jobs
        self.max_cpu_jobs = max_cpu_jobs
        self.max_provider_jobs = max_provider_jobs

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
    ) -> RuntimeExecutionRecord:
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
        self.event_bus.publish(RuntimeStarted(execution_id=execution.execution_id, schedule_id=execution.schedule_id, entry_id=execution.entry_id))

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
