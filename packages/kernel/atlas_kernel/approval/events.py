from __future__ import annotations

from dataclasses import dataclass

from ..event_types import AtlasEvent


@dataclass(frozen=True)
class ApprovalCreated(AtlasEvent):
    approval_id: str = ""
    scope: str = ""
    policy_id: str | None = None
    execution_id: str | None = None


@dataclass(frozen=True)
class ApprovalViewed(AtlasEvent):
    approval_id: str = ""
    actor: str = ""


@dataclass(frozen=True)
class ApprovalApproved(AtlasEvent):
    approval_id: str = ""
    actor: str = ""
    execution_id: str | None = None


@dataclass(frozen=True)
class ApprovalRejected(AtlasEvent):
    approval_id: str = ""
    actor: str = ""
    reason: str = ""
    execution_id: str | None = None


@dataclass(frozen=True)
class ApprovalExpired(AtlasEvent):
    approval_id: str = ""
    execution_id: str | None = None


@dataclass(frozen=True)
class ApprovalCancelled(AtlasEvent):
    approval_id: str = ""
    actor: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ApprovalEscalated(AtlasEvent):
    approval_id: str = ""
    actor: str = ""
    escalated_to: str = ""


@dataclass(frozen=True)
class ExecutionRequested(AtlasEvent):
    execution_id: str = ""
    schedule_id: str = ""
    entry_id: str = ""
    action: str = ""


@dataclass(frozen=True)
class ExecutionWaitingApproval(AtlasEvent):
    execution_id: str = ""
    schedule_id: str = ""
    entry_id: str = ""
    approval_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ExecutionApproved(AtlasEvent):
    execution_id: str = ""
    approval_id: str = ""
    actor: str = ""


@dataclass(frozen=True)
class ExecutionRejected(AtlasEvent):
    execution_id: str = ""
    approval_id: str = ""
    actor: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ExecutionExpired(AtlasEvent):
    execution_id: str = ""
    approval_id: str = ""
