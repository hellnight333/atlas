# Atlas Internal Event Bus

## Purpose

Atlas uses an internal synchronous publish/subscribe event bus to decouple worker execution from downstream observers.

Core properties:

- Publish/subscribe architecture
- Synchronous dispatch for predictable ordering and simple debugging
- Typed events (dataclasses)
- Event registry for discoverability and validation
- Optional subscribers only
- No external dependencies

No business logic may depend on any particular subscriber being present.

## Event Types

The default registered events are:

- `RunStarted`
- `RunCompleted`
- `RunFailed`
- `JobQueued`
- `JobStarted`
- `JobCompleted`
- `JobFailed`
- `AssetCreated`
- `AssetUpdated`
- `AssetDeleted`
- `AssetVersionCreated`
- `WorkflowStarted`
- `WorkflowCompleted`
- `WorkflowFailed`
- `NodeStarted`
- `NodeCompleted`
- `NodeFailed`
- `CheckpointCreated`
- `ExecutionPaused`
- `ExecutionResumed`
- `ProviderLoaded`

## Implementation

Primary module: `packages/kernel/atlas_kernel/event_bus.py`

Components:

- `AtlasEvent`: base typed event
- `EventRegistry`: tracks known event types
- `EventBus`: synchronous pub/sub transport

Subscription and publishing are typed by event class.

## Worker and Executor Integration

Worker and executor publish events instead of directly notifying other components.

- Orchestrator publishes `JobQueued`
- Worker publishes `ProviderLoaded`
- Executor publishes job/run/workflow lifecycle events
- Asset service publishes `AssetCreated`

## Async Migration Path

The API shape supports migration to async without changing publishers:

- Keep typed events and registry unchanged
- Swap sync dispatch in `EventBus.publish` with async-compatible dispatch
- Allow mixed sync/async handlers behind the same interface

Because business logic does not depend on subscribers, migration can happen incrementally.
