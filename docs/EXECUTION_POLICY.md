# Atlas Execution Policy Engine

## Objective

The Execution Policy Engine selects the optimal execution strategy for a job without executing it.

It consumes:

- Capability
- Recipe
- Requirements
- Runtime context
- Registry inventory
- Workspace and project preferences

It returns one immutable `ExecutionDecision`.

## Responsibilities

- deterministic decision making
- requirement filtering
- recipe selection
- executor selection
- provider selection
- model selection
- machine-readable explanation

## Non-Responsibilities

- no job execution
- no provider calls
- no scheduling
- no workflow orchestration

## Decision Object

`ExecutionDecision` contains:

- decision_id
- capability_id
- recipe_id
- executor_id
- provider_id
- model_id
- reason
- confidence
- timestamp

## Determinism

Given identical inputs, the engine must produce the same selected recipe, executor, provider, model, and explanation.

Tie-breaking is stable and ordered.

## Scoring

The initial implementation uses a weighted scorer over:

- offline/cloud constraints
- VRAM compatibility
- latency
- cost
- quality
- streaming support
- privacy/commercial constraints
- workspace and project preferences
- recipe metadata priority

## Events

The engine publishes:

- ExecutionPolicyEvaluated
- ExecutionDecisionCreated

Subscribers remain optional.

## API

Additive endpoints:

- POST /execution-policy/evaluate
- GET /execution-policy/decision/{id}

## Integration

The worker requests an `ExecutionDecision` before execution.
The executor receives a job that already has an execution decision and does not select provider, recipe, or model itself.
