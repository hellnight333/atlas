# ADR-0006 Workflow Engine

## Status

Accepted

## Context

Atlas requires a declarative orchestration system that can represent dependencies, parallel branches, and workflow-level lifecycle while remaining decoupled from model runtime specifics.

## Decision

Introduce a Workflow Engine that:

- Accepts declarative DAG workflow definitions.
- Validates dependency graphs and rejects cycles.
- Builds immutable execution plans.
- Schedules dependency-independent nodes concurrently.
- Delegates node execution to kernel/executor/provider chain.
- Publishes typed workflow/node/checkpoint events through the internal event bus.
- Supports retry policy placeholders and checkpoint placeholders.

## Consequences

- Atlas gains a durable orchestration boundary independent of provider or executor implementation details.
- Execution location and model specifics remain outside workflow definitions.
- Future features (conditions, loops, manual approvals, plugin nodes, distributed scheduling) can be layered on this architecture without breaking existing API contracts.
