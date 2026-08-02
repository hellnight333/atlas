from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar, cast

from .agents.events import (
    AgentAssigned,
    AgentCompleted,
    AgentCreated,
    AgentDeleted,
    AgentFailed,
    AgentMessageReceived,
    AgentMessageSent,
    AgentStarted,
    AgentStateChanged,
    AgentUpdated,
    AgentWaiting,
    MemoryAttached,
    PermissionUpdated,
    RuntimeCancelled,
    RuntimeCompleted,
    RuntimeFailed,
    RuntimePreparing,
    RuntimeProgress,
    RuntimeRunning,
    RuntimeStarted,
    RuntimeTimedOut,
    TeamCompleted,
)
from .event_types import AtlasEvent


@dataclass(frozen=True)
class RunStarted(AtlasEvent):
    run_id: str = ""
    studio: str = ""
    workflow_id: str | None = None


@dataclass(frozen=True)
class RunCompleted(AtlasEvent):
    run_id: str = ""


@dataclass(frozen=True)
class RunFailed(AtlasEvent):
    run_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class JobQueued(AtlasEvent):
    job_id: str = ""
    run_id: str = ""
    action: str = ""


@dataclass(frozen=True)
class JobStarted(AtlasEvent):
    job_id: str = ""
    run_id: str = ""
    action: str = ""


@dataclass(frozen=True)
class JobCompleted(AtlasEvent):
    job_id: str = ""
    run_id: str = ""
    provider_name: str | None = None
    asset_id: str | None = None


@dataclass(frozen=True)
class JobFailed(AtlasEvent):
    job_id: str = ""
    run_id: str = ""
    reason: str = ""
    provider_name: str | None = None


@dataclass(frozen=True)
class AssetCreated(AtlasEvent):
    asset_id: str = ""
    run_id: str = ""
    job_id: str = ""
    type: str = ""


@dataclass(frozen=True)
class AssetUpdated(AtlasEvent):
    asset_id: str = ""


@dataclass(frozen=True)
class AssetDeleted(AtlasEvent):
    asset_id: str = ""


@dataclass(frozen=True)
class AssetVersionCreated(AtlasEvent):
    asset_id: str = ""
    parent_asset_id: str = ""
    version: int = 1


@dataclass(frozen=True)
class WorkflowStarted(AtlasEvent):
    workflow_id: str = ""
    run_id: str = ""


@dataclass(frozen=True)
class WorkflowCompleted(AtlasEvent):
    workflow_id: str = ""
    run_id: str = ""


@dataclass(frozen=True)
class WorkflowFailed(AtlasEvent):
    workflow_id: str = ""
    run_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class NodeStarted(AtlasEvent):
    workflow_id: str = ""
    run_id: str = ""
    node_id: str = ""


@dataclass(frozen=True)
class NodeCompleted(AtlasEvent):
    workflow_id: str = ""
    run_id: str = ""
    node_id: str = ""
    asset_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NodeFailed(AtlasEvent):
    workflow_id: str = ""
    run_id: str = ""
    node_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class CheckpointCreated(AtlasEvent):
    workflow_id: str = ""
    run_id: str = ""
    checkpoint_id: str = ""


@dataclass(frozen=True)
class ExecutionPaused(AtlasEvent):
    workflow_id: str = ""
    run_id: str = ""


@dataclass(frozen=True)
class ExecutionResumed(AtlasEvent):
    workflow_id: str = ""
    run_id: str = ""


@dataclass(frozen=True)
class ProviderLoaded(AtlasEvent):
    provider_name: str = ""
    kind: str | None = None


@dataclass(frozen=True)
class CapabilityRegistered(AtlasEvent):
    capability_id: str = ""
    version: str = "1.0.0"


@dataclass(frozen=True)
class CapabilityUpdated(AtlasEvent):
    capability_id: str = ""
    version: str = "1.0.0"


@dataclass(frozen=True)
class RecipeRegistered(AtlasEvent):
    recipe_id: str = ""
    capability_id: str = ""
    version: str = "1.0.0"


@dataclass(frozen=True)
class RecipeSelected(AtlasEvent):
    recipe_id: str = ""
    capability_id: str = ""
    run_id: str | None = None


@dataclass(frozen=True)
class ExecutionPolicyEvaluated(AtlasEvent):
    decision_id: str = ""
    capability_id: str = ""
    executor_id: str = ""
    provider_id: str = ""


@dataclass(frozen=True)
class ExecutionDecisionCreated(AtlasEvent):
    decision_id: str = ""
    capability_id: str = ""
    executor_id: str = ""
    provider_id: str = ""


@dataclass(frozen=True)
class NodeCreated(AtlasEvent):
    node_id: str = ""
    node_type: str = ""


@dataclass(frozen=True)
class NodeArchived(AtlasEvent):
    node_id: str = ""


@dataclass(frozen=True)
class EdgeCreated(AtlasEvent):
    edge_id: str = ""
    relationship: str = ""
    from_node: str = ""
    to_node: str = ""


@dataclass(frozen=True)
class ContextBundleGenerated(AtlasEvent):
    project_id: str = ""


@dataclass(frozen=True)
class GraphSnapshotCreated(AtlasEvent):
    snapshot_id: str = ""
    scope_type: str = ""
    scope_id: str = ""


DEFAULT_EVENT_TYPES: tuple[type[AtlasEvent], ...] = (
    RunStarted,
    RunCompleted,
    RunFailed,
    JobQueued,
    JobStarted,
    JobCompleted,
    JobFailed,
    AssetCreated,
    AssetUpdated,
    AssetDeleted,
    AssetVersionCreated,
    WorkflowStarted,
    WorkflowCompleted,
    WorkflowFailed,
    NodeStarted,
    NodeCompleted,
    NodeFailed,
    CheckpointCreated,
    ExecutionPaused,
    ExecutionResumed,
    ProviderLoaded,
    CapabilityRegistered,
    CapabilityUpdated,
    RecipeRegistered,
    RecipeSelected,
    ExecutionPolicyEvaluated,
    ExecutionDecisionCreated,
    NodeCreated,
    NodeArchived,
    EdgeCreated,
    ContextBundleGenerated,
    GraphSnapshotCreated,
    AgentCreated,
    AgentUpdated,
    AgentDeleted,
    AgentStateChanged,
    AgentAssigned,
    AgentStarted,
    AgentWaiting,
    AgentMessageSent,
    AgentMessageReceived,
    AgentCompleted,
    AgentFailed,
    TeamCompleted,
    MemoryAttached,
    PermissionUpdated,
    RuntimeStarted,
    RuntimePreparing,
    RuntimeRunning,
    RuntimeProgress,
    RuntimeCompleted,
    RuntimeFailed,
    RuntimeCancelled,
    RuntimeTimedOut,
)


TAtlasEvent = TypeVar("TAtlasEvent", bound=AtlasEvent)


class EventRegistry:
    def __init__(self) -> None:
        self._types: dict[str, type[AtlasEvent]] = {}
        for event_type in DEFAULT_EVENT_TYPES:
            self.register(event_type)

    def register(self, event_type: type[AtlasEvent]) -> None:
        self._types[event_type.__name__] = event_type

    def get(self, event_name: str) -> type[AtlasEvent] | None:
        return self._types.get(event_name)

    def list(self) -> list[type[AtlasEvent]]:
        return list(self._types.values())


class EventBus:
    def __init__(self, registry: EventRegistry | None = None) -> None:
        self.registry = registry or EventRegistry()
        self._subscribers: dict[type[AtlasEvent], list[Callable[[AtlasEvent], None]]] = defaultdict(
            list
        )

    def subscribe(
        self, event_type: type[TAtlasEvent], handler: Callable[[TAtlasEvent], None]
    ) -> None:
        self._subscribers[event_type].append(cast(Callable[[AtlasEvent], None], handler))

    def publish(self, event: AtlasEvent) -> None:
        event_type = type(event)
        if self.registry.get(event_type.__name__) is None:
            self.registry.register(event_type)
        for handler in self._subscribers.get(event_type, []):
            handler(event)
