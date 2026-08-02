# Atlas Executor Layer

## Purpose

Atlas separates execution policy from provider implementation.

- Providers answer: HOW to execute model/runtime logic.
- Executors answer: WHERE execution happens.

This keeps providers location-agnostic and lets Atlas evolve execution surfaces independently.

## Abstractions

Main module: `packages/kernel/atlas_kernel/executor.py`

- `ExecutionLocationExecutor`: location strategy interface
- `JobExecutor`: orchestration-level executor that handles job lifecycle, status, events, and assets

Location executors currently available:

- `LocalExecutor`
- `DockerExecutor`
- `RemoteExecutor`
- `ClusterExecutor`
- `CloudExecutor`
- `ComfyExecutor`
- `OllamaExecutor`

Current implementations intentionally default to provider passthrough while preserving a stable contract for future location-specific runtime adapters.

## Worker Integration

Worker delegates execution through the executor interface.

- Worker handles polling and lease behavior.
- Executor handles run/job lifecycle and provider invocation.
- Provider remains unaware of execution location.

## Design Notes

- No external dependencies.
- Composition over inheritance in runtime wiring.
- New execution locations can be introduced without changing provider APIs.
