# Atlas Composition Root

## Purpose

Atlas has one composition root that constructs and wires the kernel runtime dependency graph:

- `packages/kernel/atlas_kernel/composition_root.py`

The root exports:

- `AtlasRuntime` (a frozen runtime container)
- `create_runtime(...)` (the only default-wiring entrypoint)

## Wiring Contract

Subsystem constructors receive dependencies explicitly. They do not create each other.

- `Orchestrator` receives `state_machine`, `repository`, and `event_bus`.
- `Worker` receives `repository`, `router`, `provider_manager`, `event_bus`, and `executor`.
- `JobExecutor` receives `repository`, `router`, `provider_manager`, `location_executor`, `bus`, and `asset_service`.
- `AssetService` receives `repository`, `bus`, and `storage_backend`.
- `WorkflowEngine` receives `delegate` and `bus`.

Defaults are centralized in `create_runtime(...)`.

## Shared Singletons Per Runtime

Each call to `create_runtime(...)` produces a runtime where core collaborators share one instance each:

- `EventBus`
- `Registry`
- `ProviderManager`
- `AtlasRepository`
- `ExecutionStateMachine`

The same shared `EventBus` instance is reused by:

- `runtime.orchestrator`
- `runtime.worker`
- `runtime.executor`
- `runtime.asset_service`
- `runtime.workflow_engine`

## Entry Points

Bootstraps use the composition root instead of local ad-hoc wiring:

- API: `packages/kernel/atlas_kernel/api.py`
- Worker process: `workers/gpu/run_worker.py`

## Testability

`create_runtime(...)` supports optional overrides for deterministic tests:

- `event_bus`
- `registry`
- `provider_registry`
- `repository`
- `state_machine`
- `location_executor`

This keeps tests explicit while preserving the single source of truth for defaults.
