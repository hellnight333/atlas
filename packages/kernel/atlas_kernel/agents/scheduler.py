from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..event_bus import EventBus
from ..repository import AtlasRepository
from .dependency_graph import DependencyGraph
from .events import (
    QueueUpdated,
    ScheduleCreated,
    TaskBlocked,
    TaskCancelled,
    TaskQueued,
    TaskReady,
    TaskResumed,
)
from .priorities import SchedulerPriorityEngine
from .queue import SchedulerQueue
from .schedule_models import (
    ExecutionSchedule,
    QueueEntryStatus,
    QueueUpdateResult,
    ScheduleQueueEntry,
    SchedulerRequest,
)


class AgentScheduler:
    """Deterministic scheduler. No provider/workflow execution."""

    def __init__(
        self,
        repository: AtlasRepository,
        event_bus: EventBus,
        priority_engine: SchedulerPriorityEngine | None = None,
    ) -> None:
        self.repository = repository
        self.event_bus = event_bus
        self.priority_engine = priority_engine or SchedulerPriorityEngine()

    def create_schedule(self, request: SchedulerRequest) -> ExecutionSchedule:
        edges: list[tuple[str, str]] = []
        entries: list[ScheduleQueueEntry] = []

        for step in request.steps:
            for dependency in step.dependencies:
                edges.append((dependency, step.id))

            queue_entry = ScheduleQueueEntry(
                plan_step=step,
                status=QueueEntryStatus.QUEUED,
                priority=request.priority,
                dependencies=list(step.dependencies),
                executor_hint=(
                    request.available_executors[0] if request.available_executors else None
                ),
                capability=step.capability,
            )
            entries.append(queue_entry)

        graph = DependencyGraph(edges)
        for step in request.steps:
            graph.add_node(step.id)
        graph.validate_no_cycles()

        # Deterministic sort by priority + dependency complexity + stable insertion.
        entries.sort(
            key=lambda entry: self.priority_engine.sort_key(
                entry.priority,
                len(entry.dependencies),
                entry.retry_count,
                next(i for i, step in enumerate(request.steps) if step.id == entry.plan_step.id),
            )
        )

        queue_state = SchedulerQueue(entries)
        ready_step_ids = graph.ready_nodes(completed=set())
        ready_entry_ids = [entry.id for entry in entries if entry.plan_step.id in ready_step_ids]
        queue_state.mark_ready(ready_entry_ids)

        blocked_entry_ids = [
            entry.id
            for entry in entries
            if entry.status == QueueEntryStatus.QUEUED and entry.dependencies
        ]

        estimated_seconds = sum(max(1, step.estimated_time_seconds) for step in request.steps)
        estimated_finish = datetime.now(UTC) + timedelta(seconds=estimated_seconds)

        schedule = ExecutionSchedule(
            plan_id=request.plan_id,
            agent_id=request.agent_id,
            priority=request.priority,
            estimated_finish_time=estimated_finish,
            queue_entries=entries,
            blocked_entries=blocked_entry_ids,
            parallel_groups=graph.parallel_groups(),
            queue_metadata={
                "workspace_state": request.workspace_state,
                "current_jobs": request.current_jobs,
                "running_workflows": request.running_workflows,
                "available_executors": request.available_executors,
                "execution_policy": request.execution_policy,
            },
        )

        self.repository.create_schedule(schedule)
        self.event_bus.publish(
            ScheduleCreated(
                schedule_id=schedule.schedule_id,
                plan_id=schedule.plan_id,
                agent_id=schedule.agent_id,
            )
        )
        for entry in schedule.queue_entries:
            if entry.status == QueueEntryStatus.READY:
                self.event_bus.publish(
                    TaskReady(schedule_id=schedule.schedule_id, entry_id=entry.id)
                )
            elif entry.id in schedule.blocked_entries:
                self.event_bus.publish(
                    TaskBlocked(schedule_id=schedule.schedule_id, entry_id=entry.id)
                )
            else:
                self.event_bus.publish(
                    TaskQueued(schedule_id=schedule.schedule_id, entry_id=entry.id)
                )

        return schedule

    def get_schedule(self, schedule_id: str) -> ExecutionSchedule | None:
        return self.repository.get_schedule(schedule_id)

    def get_queue(self, schedule_id: str) -> list[ScheduleQueueEntry]:
        schedule = self.repository.get_schedule(schedule_id)
        if schedule is None:
            return []
        return schedule.queue_entries

    def pause(self, schedule_id: str) -> QueueUpdateResult:
        schedule = self.repository.get_schedule(schedule_id)
        if schedule is None:
            raise ValueError("Schedule not found")
        queue = SchedulerQueue(schedule.queue_entries)
        updated_ids, tokens = queue.pause()
        schedule.resume_tokens.extend(tokens)
        self.repository.update_schedule(schedule)
        self.event_bus.publish(QueueUpdated(schedule_id=schedule_id, updated_entries=updated_ids))
        return QueueUpdateResult(schedule_id=schedule_id, updated_entries=updated_ids)

    def resume(self, schedule_id: str) -> QueueUpdateResult:
        schedule = self.repository.get_schedule(schedule_id)
        if schedule is None:
            raise ValueError("Schedule not found")
        queue = SchedulerQueue(schedule.queue_entries)
        updated_ids = queue.resume()
        for entry in schedule.queue_entries:
            if entry.status == QueueEntryStatus.QUEUED and not entry.dependencies:
                entry.status = QueueEntryStatus.READY
        self.repository.update_schedule(schedule)
        for entry_id in updated_ids:
            self.event_bus.publish(TaskResumed(schedule_id=schedule_id, entry_id=entry_id))
        return QueueUpdateResult(schedule_id=schedule_id, updated_entries=updated_ids)

    def cancel(self, schedule_id: str) -> QueueUpdateResult:
        schedule = self.repository.get_schedule(schedule_id)
        if schedule is None:
            raise ValueError("Schedule not found")
        queue = SchedulerQueue(schedule.queue_entries)
        updated_ids = queue.cancel()
        self.repository.update_schedule(schedule)
        for entry_id in updated_ids:
            self.event_bus.publish(TaskCancelled(schedule_id=schedule_id, entry_id=entry_id))
        return QueueUpdateResult(schedule_id=schedule_id, updated_entries=updated_ids)

    def retry_entry(self, schedule_id: str, entry_id: str) -> QueueUpdateResult:
        schedule = self.repository.get_schedule(schedule_id)
        if schedule is None:
            raise ValueError("Schedule not found")
        queue = SchedulerQueue(schedule.queue_entries)
        if not queue.retry(entry_id):
            raise ValueError("Queue entry not retryable")
        self.repository.update_schedule(schedule)
        self.event_bus.publish(QueueUpdated(schedule_id=schedule_id, updated_entries=[entry_id]))
        return QueueUpdateResult(schedule_id=schedule_id, updated_entries=[entry_id])
