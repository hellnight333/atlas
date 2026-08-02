from __future__ import annotations

from dataclasses import dataclass, field

from ..event_types import AtlasEvent
from .models import AgentStatus


@dataclass(frozen=True)
class AgentCreated(AtlasEvent):
    agent_id: str = ""
    project_id: str | None = None
    workspace_id: str | None = None


@dataclass(frozen=True)
class AgentUpdated(AtlasEvent):
    agent_id: str = ""


@dataclass(frozen=True)
class AgentDeleted(AtlasEvent):
    agent_id: str = ""


@dataclass(frozen=True)
class AgentStateChanged(AtlasEvent):
    agent_id: str = ""
    previous_status: AgentStatus = AgentStatus.IDLE
    current_status: AgentStatus = AgentStatus.IDLE


@dataclass(frozen=True)
class MemoryAttached(AtlasEvent):
    agent_id: str = ""
    memory_id: str = ""
    reference_id: str = ""


@dataclass(frozen=True)
class PermissionUpdated(AtlasEvent):
    agent_id: str = ""


@dataclass(frozen=True)
class ScheduleCreated(AtlasEvent):
    schedule_id: str = ""
    plan_id: str = ""
    agent_id: str = ""


@dataclass(frozen=True)
class QueueUpdated(AtlasEvent):
    schedule_id: str = ""
    updated_entries: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TaskQueued(AtlasEvent):
    schedule_id: str = ""
    entry_id: str = ""


@dataclass(frozen=True)
class TaskBlocked(AtlasEvent):
    schedule_id: str = ""
    entry_id: str = ""


@dataclass(frozen=True)
class TaskReady(AtlasEvent):
    schedule_id: str = ""
    entry_id: str = ""


@dataclass(frozen=True)
class TaskResumed(AtlasEvent):
    schedule_id: str = ""
    entry_id: str = ""


@dataclass(frozen=True)
class TaskCancelled(AtlasEvent):
    schedule_id: str = ""
    entry_id: str = ""


@dataclass(frozen=True)
class TaskCompleted(AtlasEvent):
    schedule_id: str = ""
    entry_id: str = ""


@dataclass(frozen=True)
class RuntimeStarted(AtlasEvent):
    execution_id: str = ""
    schedule_id: str = ""
    entry_id: str = ""


@dataclass(frozen=True)
class RuntimePreparing(AtlasEvent):
    execution_id: str = ""
    schedule_id: str = ""
    entry_id: str = ""


@dataclass(frozen=True)
class RuntimeRunning(AtlasEvent):
    execution_id: str = ""
    schedule_id: str = ""
    entry_id: str = ""


@dataclass(frozen=True)
class RuntimeProgress(AtlasEvent):
    execution_id: str = ""
    schedule_id: str = ""
    entry_id: str = ""
    heartbeat_at: str = ""
    detail: str = "heartbeat"


@dataclass(frozen=True)
class RuntimeCompleted(AtlasEvent):
    execution_id: str = ""
    schedule_id: str = ""
    entry_id: str = ""
    asset_id: str | None = None


@dataclass(frozen=True)
class RuntimeFailed(AtlasEvent):
    execution_id: str = ""
    schedule_id: str = ""
    entry_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class RuntimeCancelled(AtlasEvent):
    execution_id: str = ""
    schedule_id: str = ""
    entry_id: str = ""


@dataclass(frozen=True)
class RuntimeTimedOut(AtlasEvent):
    execution_id: str = ""
    schedule_id: str = ""
    entry_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class AgentAssigned(AtlasEvent):
    team_id: str = ""
    assignment_id: str = ""
    agent_id: str = ""


@dataclass(frozen=True)
class AgentStarted(AtlasEvent):
    team_id: str = ""
    assignment_id: str = ""
    agent_id: str = ""


@dataclass(frozen=True)
class AgentWaiting(AtlasEvent):
    team_id: str = ""
    assignment_id: str = ""
    agent_id: str = ""


@dataclass(frozen=True)
class AgentMessageSent(AtlasEvent):
    team_id: str = ""
    message_id: str = ""
    sender: str = ""
    receiver: str = ""


@dataclass(frozen=True)
class AgentMessageReceived(AtlasEvent):
    team_id: str = ""
    message_id: str = ""
    sender: str = ""
    receiver: str = ""


@dataclass(frozen=True)
class AgentCompleted(AtlasEvent):
    team_id: str = ""
    assignment_id: str = ""
    agent_id: str = ""


@dataclass(frozen=True)
class AgentFailed(AtlasEvent):
    team_id: str = ""
    assignment_id: str = ""
    agent_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class TeamCompleted(AtlasEvent):
    team_id: str = ""
