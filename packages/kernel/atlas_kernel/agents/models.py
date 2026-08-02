from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentPermission(StrEnum):
    READ_ASSETS = "read_assets"
    WRITE_ASSETS = "write_assets"
    EXECUTE_WORKFLOW = "execute_workflow"
    REVIEW_ASSETS = "review_assets"
    PUBLISH_ASSETS = "publish_assets"
    DELETE_ASSETS = "delete_assets"
    MODIFY_PROJECT = "modify_project"
    MANAGE_AGENTS = "manage_agents"


class AgentRole(StrEnum):
    RESEARCH = "research"
    PLANNER = "planner"
    WRITER = "writer"
    REVIEWER = "reviewer"
    IMAGE = "image"
    VIDEO = "video"
    DEVELOPER = "developer"
    OPERATOR = "operator"


class AgentCapabilitySet(BaseModel):
    role: AgentRole
    capabilities: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    permissions: list[AgentPermission] = Field(default_factory=list)
    resource_limits: dict[str, int] = Field(default_factory=dict)


class AgentTeamStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentAssignmentStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentMessageType(StrEnum):
    TASK_ASSIGNMENT = "TaskAssignment"
    PROGRESS_UPDATE = "ProgressUpdate"
    QUESTION = "Question"
    ANSWER = "Answer"
    APPROVAL_REQUEST = "ApprovalRequest"
    APPROVAL_GRANTED = "ApprovalGranted"
    APPROVAL_REJECTED = "ApprovalRejected"
    ASSET_REFERENCE = "AssetReference"
    COMPLETION = "Completion"
    FAILURE = "Failure"


class AgentMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    sender: str
    receiver: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    type: AgentMessageType
    payload: dict[str, object] = Field(default_factory=dict)
    correlation_id: str | None = None
    reply_to: str | None = None


class AgentMailbox(BaseModel):
    agent_id: str
    pending_messages: list[AgentMessage] = Field(default_factory=list)
    history: list[AgentMessage] = Field(default_factory=list)


class AgentConversation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    team_id: str
    participant_ids: list[str] = Field(default_factory=list)
    message_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentAssignment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    team_id: str
    agent_id: str
    role: AgentRole
    title: str
    status: AgentAssignmentStatus = AgentAssignmentStatus.PENDING
    capabilities: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    permissions: list[AgentPermission] = Field(default_factory=list)
    resource_limits: dict[str, int] = Field(default_factory=dict)
    action: str
    payload: dict[str, object] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    mailbox_id: str
    schedule_id: str | None = None
    runtime_execution_id: str | None = None
    result_asset_id: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentTeam(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    project_id: str | None = None
    workspace_id: str | None = None
    status: AgentTeamStatus = AgentTeamStatus.PENDING
    assignments: list[AgentAssignment] = Field(default_factory=list)
    conversation_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    role: str
    workspace_id: str | None = None
    project_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    memory_id: str | None = None
    permission_set: list[AgentPermission] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    role: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    capabilities: list[str] | None = None
    status: AgentStatus | None = None
    memory_id: str | None = None
    permission_set: list[AgentPermission] | None = None


class Agent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    role: str
    workspace_id: str | None = None
    project_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    memory_id: str
    permission_set: list[AgentPermission] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


MemoryReferenceKind = Literal[
    "conversation",
    "research",
    "image",
    "workflow",
    "review",
    "workspace",
]


class AgentMemoryReference(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    memory_id: str
    agent_id: str
    kind: MemoryReferenceKind
    asset_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


ALLOWED_STATUS_TRANSITIONS: dict[AgentStatus, set[AgentStatus]] = {
    AgentStatus.IDLE: {
        AgentStatus.PLANNING,
        AgentStatus.EXECUTING,
        AgentStatus.PAUSED,
        AgentStatus.COMPLETED,
        AgentStatus.FAILED,
        AgentStatus.CANCELLED,
    },
    AgentStatus.PLANNING: {
        AgentStatus.IDLE,
        AgentStatus.EXECUTING,
        AgentStatus.PAUSED,
        AgentStatus.COMPLETED,
        AgentStatus.FAILED,
        AgentStatus.CANCELLED,
    },
    AgentStatus.EXECUTING: {
        AgentStatus.IDLE,
        AgentStatus.PLANNING,
        AgentStatus.PAUSED,
        AgentStatus.COMPLETED,
        AgentStatus.FAILED,
        AgentStatus.CANCELLED,
    },
    AgentStatus.PAUSED: {
        AgentStatus.IDLE,
        AgentStatus.PLANNING,
        AgentStatus.EXECUTING,
        AgentStatus.COMPLETED,
        AgentStatus.FAILED,
        AgentStatus.CANCELLED,
    },
    AgentStatus.COMPLETED: {
        AgentStatus.IDLE,
        AgentStatus.PLANNING,
    },
    AgentStatus.FAILED: {
        AgentStatus.IDLE,
        AgentStatus.PLANNING,
    },
    AgentStatus.CANCELLED: {
        AgentStatus.IDLE,
        AgentStatus.PLANNING,
    },
}
