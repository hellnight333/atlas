# 0001 - Architecture Foundation for Atlas

## Status

Accepted

## Context

Atlas needs a scalable platform foundation that can evolve without adding feature-specific coupling. The kernel must separate event distribution, execution, assets, and registry concerns so future capabilities can compose cleanly.

## Decision

Implement the following foundational subsystems:

- `EventBus` for typed event propagation inside the kernel.
- `Executor` layer for job execution that is decoupled from polling and worker lifecycle.
- `AssetService` for asset creation, metadata, and lineage.
- `Registry` as the canonical catalog for actions, providers, and recipes.
- Architecture Decision Records for capturing design tradeoffs and domain rules.

## Consequences

- The kernel can evolve worker orchestration and provider routing independently.
- Event-driven extensions and observability can be added without touching core business logic.
- Assets are first-class entities with persistence and event notifications.
- Design decisions are documented and reviewable.
