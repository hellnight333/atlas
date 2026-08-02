from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..agents.runtime import ApprovalVerdict
from ..agents.schedule_models import ExecutionSchedule, ScheduleQueueEntry
from .events import (
    ExecutionApproved,
    ExecutionExpired,
    ExecutionRejected,
    ExecutionRequested,
    ExecutionWaitingApproval,
)
from .models import ApprovalContext, ApprovalScope, ApprovalState
from .service import ApprovalService

if TYPE_CHECKING:
    from ..event_bus import EventBus


class RuntimeApprovalGate:
    """Bridges the approval domain to the runtime.

    On each check it either finds an existing decision for the entry or asks the
    policy engine whether one is needed. It never decides on its own: with no
    matching policy the action proceeds, and with a policy match it creates a
    pending request and withholds consent until a human acts.
    """

    def __init__(self, service: ApprovalService, event_bus: EventBus) -> None:
        self.service = service
        self.event_bus = event_bus

    def check(
        self, schedule: ExecutionSchedule, entry: ScheduleQueueEntry, execution_id: str
    ) -> ApprovalVerdict:
        self.event_bus.publish(
            ExecutionRequested(
                execution_id=execution_id,
                schedule_id=schedule.schedule_id,
                entry_id=entry.id,
                action=entry.plan_step.action,
            )
        )

        existing = self._existing_request(schedule.schedule_id, entry.id)
        if existing is not None:
            return self._verdict_for(existing, schedule, entry)

        context = self._context(schedule, entry, execution_id)
        evaluation = self.service.evaluate(context)
        if not evaluation.required:
            return ApprovalVerdict(allowed=True, reason=evaluation.reason)

        request = self.service.create_request(
            title=f"{entry.plan_step.action}: {entry.plan_step.description}"[:200],
            context=context,
            evaluation=evaluation,
            priority=self._priority(entry),
        )
        self.event_bus.publish(
            ExecutionWaitingApproval(
                execution_id=context.execution_id or "",
                schedule_id=schedule.schedule_id,
                entry_id=entry.id,
                approval_id=request.id,
                reason=request.reason,
            )
        )
        return ApprovalVerdict(allowed=False, approval_id=request.id, reason=request.reason)

    def _verdict_for(
        self, request: Any, schedule: ExecutionSchedule, entry: ScheduleQueueEntry
    ) -> ApprovalVerdict:
        if request.state is ApprovalState.APPROVED:
            self.event_bus.publish(
                ExecutionApproved(
                    execution_id=request.execution_id or "",
                    approval_id=request.id,
                    actor=self._deciding_actor(request),
                )
            )
            return ApprovalVerdict(allowed=True, approval_id=request.id, reason="approved")

        if request.state is ApprovalState.REJECTED:
            self.event_bus.publish(
                ExecutionRejected(
                    execution_id=request.execution_id or "",
                    approval_id=request.id,
                    actor=self._deciding_actor(request),
                    reason=self._last_comment(request) or "rejected",
                )
            )
            return ApprovalVerdict(
                allowed=False,
                approval_id=request.id,
                rejected=True,
                reason=self._last_comment(request) or "approval rejected",
            )

        if request.state is ApprovalState.EXPIRED:
            self.event_bus.publish(
                ExecutionExpired(execution_id=request.execution_id or "", approval_id=request.id)
            )
            return ApprovalVerdict(
                allowed=False,
                approval_id=request.id,
                expired=True,
                reason="approval expired",
            )

        if request.state is ApprovalState.CANCELLED:
            return ApprovalVerdict(
                allowed=False,
                approval_id=request.id,
                rejected=True,
                reason="approval cancelled",
            )

        return ApprovalVerdict(allowed=False, approval_id=request.id, reason=request.reason)

    def _existing_request(self, schedule_id: str, entry_id: str) -> Any | None:
        matches = [
            request
            for request in self.service.list_requests()
            if request.schedule_id == schedule_id and request.entry_id == entry_id
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda r: r.created_at)[-1]

    def _context(
        self, schedule: ExecutionSchedule, entry: ScheduleQueueEntry, execution_id: str
    ) -> ApprovalContext:
        payload = dict(entry.plan_step.payload)
        return ApprovalContext(
            action=entry.plan_step.action,
            scopes=self._declared_scopes(payload),
            estimated_cost=float(
                payload.get("estimated_cost", entry.plan_step.estimated_cost_usd or 0.0)
            ),
            project_id=self._project_id(schedule),
            workspace_id=schedule.queue_metadata.get("workspace_id"),
            agent_id=schedule.agent_id,
            execution_id=execution_id,
            schedule_id=schedule.schedule_id,
            entry_id=entry.id,
            plan_id=schedule.plan_id,
            requested_by=str(schedule.queue_metadata.get("requested_by", "system")),
            payload=payload,
            metadata={"capability": entry.capability},
        )

    def _declared_scopes(self, payload: dict[str, Any]) -> list[ApprovalScope]:
        """Scopes are declared by the caller, never inferred from the action name."""
        declared = payload.get("approval_scopes", [])
        scopes: list[ApprovalScope] = []
        for value in declared if isinstance(declared, list) else []:
            try:
                scopes.append(ApprovalScope(value))
            except ValueError:
                continue
        return scopes

    def _project_id(self, schedule: ExecutionSchedule) -> str | None:
        explicit = schedule.queue_metadata.get("project_id")
        if explicit:
            return str(explicit)
        agent = (
            self.service.repository.get_agent(schedule.agent_id)
            if self.service.repository is not None
            else None
        )
        return agent.project_id if agent is not None else None

    def _priority(self, entry: ScheduleQueueEntry) -> int:
        return {"immediate": 100, "high": 50, "normal": 0, "low": -10, "background": -50}.get(
            entry.priority.value, 0
        )

    def _deciding_actor(self, request: Any) -> str:
        return request.decisions[-1].actor if request.decisions else "system"

    def _last_comment(self, request: Any) -> str | None:
        return request.decisions[-1].comment if request.decisions else None
