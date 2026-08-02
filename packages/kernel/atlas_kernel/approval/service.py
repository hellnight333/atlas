from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .events import (
    ApprovalApproved,
    ApprovalCancelled,
    ApprovalCreated,
    ApprovalEscalated,
    ApprovalExpired,
    ApprovalRejected,
    ApprovalViewed,
)
from .models import (
    TERMINAL_APPROVAL_STATES,
    ApprovalContext,
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalEvaluation,
    ApprovalHistoryEvent,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalScope,
    ApprovalState,
)
from .policies import ApprovalPolicyEngine

if TYPE_CHECKING:
    from ..event_bus import EventBus
    from ..repository import AtlasRepository


class ApprovalError(RuntimeError):
    """Raised when a decision is not permitted."""


class SelfApprovalError(ApprovalError):
    """A requester may never approve their own request."""


class ApprovalService:
    """Owns approval lifecycle. Decides nothing on its own — a human actor is
    required for every state transition out of PENDING, except expiry, which is
    driven by wall-clock time set by policy."""

    def __init__(
        self,
        repository: AtlasRepository,
        event_bus: EventBus,
        policy_engine: ApprovalPolicyEngine | None = None,
    ) -> None:
        self.repository = repository
        self.event_bus = event_bus
        self.policy_engine = policy_engine or ApprovalPolicyEngine()

    # ------------------------------------------------------------------
    # Policy evaluation
    # ------------------------------------------------------------------

    def evaluate(self, context: ApprovalContext) -> ApprovalEvaluation:
        policies = self.repository.list_approval_policies()
        return self.policy_engine.evaluate(policies, context)

    def list_policies(
        self, project_id: str | None = None, workspace_id: str | None = None
    ) -> list[ApprovalPolicy]:
        policies = self.repository.list_approval_policies()
        if project_id is not None:
            policies = [p for p in policies if p.project_id in (None, project_id)]
        if workspace_id is not None:
            policies = [p for p in policies if p.workspace_id in (None, workspace_id)]
        return policies

    def upsert_policy(self, policy: ApprovalPolicy, actor: str = "system") -> ApprovalPolicy:
        stored = policy.model_copy(update={"updated_at": datetime.now(UTC)})
        self.repository.upsert_approval_policy(stored)
        return stored

    # ------------------------------------------------------------------
    # Request lifecycle
    # ------------------------------------------------------------------

    def create_request(
        self,
        *,
        title: str,
        context: ApprovalContext,
        evaluation: ApprovalEvaluation | None = None,
        priority: int = 0,
        run_id: str | None = None,
        job_id: str | None = None,
        asset_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        evaluation = evaluation or self.evaluate(context)
        now = datetime.now(UTC)
        expires_at = (
            now + timedelta(seconds=evaluation.expires_after_seconds)
            if evaluation.expires_after_seconds
            else None
        )

        request = ApprovalRequest(
            title=title,
            action=context.action,
            scopes=list(context.scopes),
            estimated_cost=context.estimated_cost,
            reason=evaluation.reason,
            policy_id=evaluation.policy_id,
            policy_name=evaluation.policy_name,
            required_approvers=list(evaluation.required_approvers),
            approvals_required=max(1, evaluation.approvals_required),
            priority=priority,
            project_id=context.project_id,
            workspace_id=context.workspace_id,
            agent_id=context.agent_id,
            execution_id=context.execution_id,
            schedule_id=context.schedule_id,
            entry_id=context.entry_id,
            run_id=run_id,
            job_id=job_id,
            asset_id=asset_id,
            payload=dict(context.payload),
            metadata=metadata or {},
            requested_by=context.requested_by,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        self.repository.create_approval_request(request)
        self._record(
            request.id,
            "created",
            actor=request.requested_by,
            to_state=ApprovalState.PENDING,
            metadata={"policy_id": evaluation.policy_id, "reason": evaluation.reason},
        )
        self.event_bus.publish(
            ApprovalCreated(
                approval_id=request.id,
                scope=",".join(s.value for s in request.scopes),
                policy_id=request.policy_id,
                execution_id=request.execution_id,
            )
        )
        return request

    def get(self, approval_id: str) -> ApprovalRequest | None:
        request = self.repository.get_approval_request(approval_id)
        if request is not None:
            request = self._expire_if_due(request)
        return request

    def list_pending(
        self, project_id: str | None = None, workspace_id: str | None = None
    ) -> list[ApprovalRequest]:
        requests = [
            self._expire_if_due(r)
            for r in self.repository.list_approval_requests(
                state=ApprovalState.PENDING, project_id=project_id, workspace_id=workspace_id
            )
        ]
        pending = [r for r in requests if r.state is ApprovalState.PENDING]
        return sorted(pending, key=lambda r: (-r.priority, r.created_at, r.id))

    def list_requests(
        self,
        state: ApprovalState | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
    ) -> list[ApprovalRequest]:
        requests = [
            self._expire_if_due(r)
            for r in self.repository.list_approval_requests(
                state=None, project_id=project_id, workspace_id=workspace_id
            )
        ]
        if state is not None:
            requests = [r for r in requests if r.state is state]
        return sorted(requests, key=lambda r: (-r.priority, r.created_at, r.id))

    def list_history(self, approval_id: str | None = None) -> list[ApprovalHistoryEvent]:
        return self.repository.list_approval_history(approval_id=approval_id)

    def mark_viewed(self, approval_id: str, actor: str) -> ApprovalRequest:
        request = self._require(approval_id)
        if actor not in request.viewed_by:
            request.viewed_by.append(actor)
            request.updated_at = datetime.now(UTC)
            self.repository.update_approval_request(request)
            self._record(approval_id, "viewed", actor=actor)
            self.event_bus.publish(ApprovalViewed(approval_id=approval_id, actor=actor))
        return request

    def approve(
        self, approval_id: str, actor: str, comment: str | None = None
    ) -> ApprovalRequest:
        request = self._require_pending(approval_id)
        self._guard_actor(request, actor)

        if any(
            d.actor == actor and d.decision is ApprovalDecisionType.APPROVE
            for d in request.decisions
        ):
            raise ApprovalError(f"{actor} has already approved {approval_id}")

        decision = ApprovalDecision(
            decision=ApprovalDecisionType.APPROVE, actor=actor, comment=comment
        )
        request.decisions.append(decision)
        request.updated_at = datetime.now(UTC)

        satisfied = request.approval_count >= request.approvals_required
        if satisfied:
            request.state = ApprovalState.APPROVED
            request.decided_at = request.updated_at

        self.repository.update_approval_request(request)
        self._record(
            approval_id,
            "approved" if satisfied else "approval_recorded",
            actor=actor,
            comment=comment,
            from_state=ApprovalState.PENDING,
            to_state=request.state,
            metadata={
                "approvals": request.approval_count,
                "required": request.approvals_required,
            },
        )
        if satisfied:
            self.event_bus.publish(
                ApprovalApproved(
                    approval_id=approval_id, actor=actor, execution_id=request.execution_id
                )
            )
        return request

    def reject(
        self, approval_id: str, actor: str, comment: str | None = None
    ) -> ApprovalRequest:
        request = self._require_pending(approval_id)
        self._guard_actor(request, actor)

        now = datetime.now(UTC)
        request.decisions.append(
            ApprovalDecision(
                decision=ApprovalDecisionType.REJECT, actor=actor, comment=comment
            )
        )
        request.state = ApprovalState.REJECTED
        request.decided_at = now
        request.updated_at = now
        self.repository.update_approval_request(request)
        self._record(
            approval_id,
            "rejected",
            actor=actor,
            comment=comment,
            from_state=ApprovalState.PENDING,
            to_state=ApprovalState.REJECTED,
        )
        self.event_bus.publish(
            ApprovalRejected(
                approval_id=approval_id,
                actor=actor,
                reason=comment or "",
                execution_id=request.execution_id,
            )
        )
        return request

    def request_changes(
        self, approval_id: str, actor: str, comment: str | None = None
    ) -> ApprovalRequest:
        """Records a change request without deciding. The request stays pending."""
        request = self._require_pending(approval_id)
        self._guard_actor(request, actor)
        request.decisions.append(
            ApprovalDecision(
                decision=ApprovalDecisionType.REQUEST_CHANGES, actor=actor, comment=comment
            )
        )
        request.updated_at = datetime.now(UTC)
        self.repository.update_approval_request(request)
        self._record(approval_id, "changes_requested", actor=actor, comment=comment)
        return request

    def cancel(
        self, approval_id: str, actor: str = "system", comment: str | None = None
    ) -> ApprovalRequest:
        request = self._require_pending(approval_id)
        now = datetime.now(UTC)
        request.state = ApprovalState.CANCELLED
        request.decided_at = now
        request.updated_at = now
        self.repository.update_approval_request(request)
        self._record(
            approval_id,
            "cancelled",
            actor=actor,
            comment=comment,
            from_state=ApprovalState.PENDING,
            to_state=ApprovalState.CANCELLED,
        )
        self.event_bus.publish(
            ApprovalCancelled(approval_id=approval_id, actor=actor, reason=comment or "")
        )
        return request

    def expire(self, approval_id: str) -> ApprovalRequest:
        request = self._require(approval_id)
        if request.state is not ApprovalState.PENDING:
            return request
        return self._expire(request)

    def escalate(self, approval_id: str, actor: str, escalated_to: str) -> ApprovalRequest:
        request = self._require_pending(approval_id)
        if escalated_to not in request.required_approvers:
            request.required_approvers.append(escalated_to)
        request.updated_at = datetime.now(UTC)
        self.repository.update_approval_request(request)
        self._record(
            approval_id,
            "escalated",
            actor=actor,
            metadata={"escalated_to": escalated_to},
        )
        self.event_bus.publish(
            ApprovalEscalated(approval_id=approval_id, actor=actor, escalated_to=escalated_to)
        )
        return request

    def expire_due(self) -> list[ApprovalRequest]:
        """Sweep. Returns the requests this call transitioned to EXPIRED."""
        expired: list[ApprovalRequest] = []
        for request in self.repository.list_approval_requests(state=ApprovalState.PENDING):
            if self._is_due(request):
                expired.append(self._expire(request))
        return expired

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require(self, approval_id: str) -> ApprovalRequest:
        request = self.repository.get_approval_request(approval_id)
        if request is None:
            raise ApprovalError(f"Approval request not found: {approval_id}")
        return request

    def _require_pending(self, approval_id: str) -> ApprovalRequest:
        request = self._expire_if_due(self._require(approval_id))
        if request.state in TERMINAL_APPROVAL_STATES:
            raise ApprovalError(
                f"Approval {approval_id} is already {request.state.value} and cannot be changed"
            )
        return request

    def _guard_actor(self, request: ApprovalRequest, actor: str) -> None:
        if not actor or not actor.strip():
            raise ApprovalError("An approval decision requires an actor")
        if actor == request.requested_by:
            raise SelfApprovalError(
                f"{actor} requested this approval and may not decide it"
            )
        if request.required_approvers and actor not in request.required_approvers:
            raise ApprovalError(
                f"{actor} is not an approver for {request.id}"
            )

    def _is_due(self, request: ApprovalRequest) -> bool:
        return (
            request.state is ApprovalState.PENDING
            and request.expires_at is not None
            and datetime.now(UTC) >= request.expires_at
        )

    def _expire_if_due(self, request: ApprovalRequest) -> ApprovalRequest:
        return self._expire(request) if self._is_due(request) else request

    def _expire(self, request: ApprovalRequest) -> ApprovalRequest:
        now = datetime.now(UTC)
        request.state = ApprovalState.EXPIRED
        request.decided_at = now
        request.updated_at = now
        self.repository.update_approval_request(request)
        self._record(
            request.id,
            "expired",
            from_state=ApprovalState.PENDING,
            to_state=ApprovalState.EXPIRED,
        )
        self.event_bus.publish(
            ApprovalExpired(approval_id=request.id, execution_id=request.execution_id)
        )
        return request

    def _record(
        self,
        approval_id: str,
        event_type: str,
        *,
        actor: str = "system",
        comment: str | None = None,
        from_state: ApprovalState | None = None,
        to_state: ApprovalState | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.repository.create_approval_history_event(
            ApprovalHistoryEvent(
                approval_id=approval_id,
                event_type=event_type,
                actor=actor,
                comment=comment,
                from_state=from_state,
                to_state=to_state,
                metadata=metadata or {},
            )
        )


__all__ = [
    "ApprovalError",
    "ApprovalService",
    "SelfApprovalError",
    "ApprovalScope",
]
