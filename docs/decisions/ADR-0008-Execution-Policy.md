# ADR-0008 Execution Policy

## Status

Accepted

## Context

Atlas needs a deterministic decision boundary between capability intent and execution.
Without this boundary, workers or executors would keep making ad-hoc routing choices, which breaks the frozen architecture.

## Decision

Introduce an Execution Policy Engine that:

- consumes capability request, optional recipe, requirements, runtime context, and registry inventory
- returns an immutable `ExecutionDecision`
- publishes typed evaluation and creation events
- does not execute, schedule, or orchestrate jobs

Workers must obtain an execution decision before handing a job to the executor.
Executors consume the completed decision and perform location-specific execution only.

## Consequences

- provider selection is centralized into a deterministic policy service
- executor/provider boundaries remain clean
- future optimization strategies can extend scoring without changing workflow or executor contracts
- every execution path can be audited through persisted execution decisions
