from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ApprovalScope(StrEnum):
    """What kind of capability an action exercises. Supplied by the caller —
    the policy engine never infers scope from an action name."""

    EXTERNAL_API = "external_api"
    FILESYSTEM_WRITE = "filesystem_write"
    NETWORK = "network"
    PROVIDER_COST = "provider_cost"
    PROJECT_PUBLISH = "project_publish"
    DELETE = "delete"
    PLUGIN_ACTION = "plugin_action"
    ENTERPRISE = "enterprise"


class ApprovalState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_APPROVAL_STATES: frozenset[ApprovalState] = frozenset(
    {
        ApprovalState.APPROVED,
        ApprovalState.REJECTED,
        ApprovalState.CANCELLED,
        ApprovalState.EXPIRED,
    }
)


class ApprovalDecisionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class ApprovalDecision(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    decision: ApprovalDecisionType
    actor: str
    comment: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalPolicyMode(StrEnum):
    ALWAYS = "always"
    NEVER = "never"
    SCOPED = "scoped"


class ApprovalCondition(BaseModel):
    """Declarative predicate over the approval context. No rule is hardcoded in
    the engine; every rule is data supplied by a policy."""

    field: str
    operator: str
    value: Any = None


class ApprovalPolicy(BaseModel):
    id: str = Field(default_factory=lambda: f"approval-policy-{uuid4().hex[:12]}")
    name: str
    description: str = ""
    mode: ApprovalPolicyMode = ApprovalPolicyMode.SCOPED
    scopes: list[ApprovalScope] = Field(default_factory=list)
    cost_threshold: float | None = None
    conditions: list[ApprovalCondition] = Field(default_factory=list)
    required_approvers: list[str] = Field(default_factory=list)
    approvals_required: int = 1
    expires_after_seconds: int | None = None
    project_id: str | None = None
    workspace_id: str | None = None
    priority: int = 0
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalContext(BaseModel):
    """Everything the policy engine is allowed to reason about."""

    action: str = ""
    scopes: list[ApprovalScope] = Field(default_factory=list)
    estimated_cost: float = 0.0
    project_id: str | None = None
    workspace_id: str | None = None
    agent_id: str | None = None
    execution_id: str | None = None
    schedule_id: str | None = None
    entry_id: str | None = None
    plan_id: str | None = None
    requested_by: str = "system"
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: f"approval-{uuid4().hex[:12]}")
    title: str
    state: ApprovalState = ApprovalState.PENDING
    action: str = ""
    scopes: list[ApprovalScope] = Field(default_factory=list)
    estimated_cost: float = 0.0
    reason: str = ""
    policy_id: str | None = None
    policy_name: str | None = None
    required_approvers: list[str] = Field(default_factory=list)
    approvals_required: int = 1
    decisions: list[ApprovalDecision] = Field(default_factory=list)
    viewed_by: list[str] = Field(default_factory=list)
    priority: int = 0
    project_id: str | None = None
    workspace_id: str | None = None
    agent_id: str | None = None
    execution_id: str | None = None
    schedule_id: str | None = None
    entry_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    asset_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    decided_at: datetime | None = None

    @property
    def approval_count(self) -> int:
        return sum(1 for d in self.decisions if d.decision is ApprovalDecisionType.APPROVE)

    @property
    def is_pending(self) -> bool:
        return self.state is ApprovalState.PENDING


class ApprovalHistoryEvent(BaseModel):
    """Append-only. Never updated, never deleted."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    approval_id: str
    event_type: str
    actor: str = "system"
    comment: str | None = None
    from_state: ApprovalState | None = None
    to_state: ApprovalState | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalEvaluation(BaseModel):
    """Result of running the policy engine against a context."""

    required: bool
    policy_id: str | None = None
    policy_name: str | None = None
    reason: str = ""
    required_approvers: list[str] = Field(default_factory=list)
    approvals_required: int = 1
    expires_after_seconds: int | None = None
    matched_scopes: list[ApprovalScope] = Field(default_factory=list)
