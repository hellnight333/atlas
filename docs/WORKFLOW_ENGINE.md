# Atlas Workflow Engine

## Objective

The Workflow Engine executes declarative DAG workflows and acts as Atlas orchestration brain.

It determines execution order but does not execute models directly.

Execution delegation path:

Workflow Engine -> Kernel -> Executor -> Provider -> Model

## Core Concepts

- WorkflowDefinition
- ExecutionPlan (immutable)
- WorkflowNode
- Dependency Edge
- WorkflowExecution
- ExecutionState
- RetryPolicy
- Checkpoint
- Condition (placeholder)

## DAG Model

A workflow is a graph, not a list.

- Nodes represent jobs.
- Edges represent dependencies.
- A node runs only after all dependencies complete.
- Cycles are rejected during validation.

## Parallel Scheduling

The engine computes DAG levels.

Nodes in the same level are dependency-independent and scheduled concurrently.

## Execution States

- pending
- running
- completed
- failed
- paused
- cancelled
- skipped

## Retry Policy

Each node supports:

- `max_retries`
- `retry_delay_seconds`
- `failure_strategy` (`fail_fast` or `continue`)

Current implementation provides placeholder-level retry behavior with no provider-specific logic.

## Checkpoints

Checkpoint architecture is implemented with snapshot placeholders to support future resume and migration workflows.

## Events

Workflow Engine publishes typed events:

- `WorkflowStarted`
- `WorkflowCompleted`
- `WorkflowFailed`
- `NodeStarted`
- `NodeCompleted`
- `NodeFailed`
- `CheckpointCreated`
- `ExecutionPaused`
- `ExecutionResumed`

Subscribers are optional.

## API (Additive)

- `POST /workflow-engine/workflows`
- `POST /workflow-engine/workflows/validate`
- `POST /workflow-engine/workflows/{workflow_definition_id}/execute`
- `POST /workflow-engine/executions/{execution_id}/pause`
- `POST /workflow-engine/executions/{execution_id}/resume`
- `POST /workflow-engine/executions/{execution_id}/cancel`
- `GET /workflow-engine/executions/{execution_id}/plan`

Existing APIs remain backward compatible.
