# ADR-0007 Capability Layer

## Status

Accepted

## Context

Workflow definitions must remain stable while provider, model, and execution choices evolve.
Without a semantic layer, workflow nodes drift toward provider coupling and become costly to migrate.

## Decision

Introduce a dedicated Capability Layer that:

- Represents user intent as provider-agnostic capabilities.
- Associates capabilities with versioned recipe definitions.
- Stores requirement and compatibility metadata.
- Exposes additive APIs for capability and recipe registration and discovery.
- Publishes typed capability events through the internal event bus.

Capability selection remains delegated to policy/executor/provider layers.
The capability layer does not execute jobs and contains no model runtime logic.

## Consequences

- Workflow definitions can stay intent-first as implementations change.
- Providers and executors remain replaceable without workflow schema churn.
- The architecture gains an explicit extension seam for plugin capability registration and marketplace/discovery features.
- Backward compatibility is preserved because existing run/workflow/provider APIs remain unchanged.
