# Atlas Platform Status

## Frozen Foundation

The following architectural subsystems are currently part of the frozen platform foundation:

- Core Domain
- Event Bus
- Registry
- Composition Root
- Executor Layer
- Workflow Engine
- Asset System
- Capability Layer
- Execution Policy Engine

## Current Execution Path

Workflow -> Capability -> Recipe -> Execution Policy -> Execution Decision -> Executor -> Provider -> Model -> Asset

## Automation Entry Path

Trigger -> Conditions -> Planner -> Scheduler -> Runtime -> Worker

Automation orchestrates existing subsystems only. It never calls a provider and never bypasses
the Scheduler. See `AUTOMATION_ENGINE.md`.

## Change Governance

Breaking architectural changes require an ADR and approval before implementation.

## Engineering Controls

The platform now expects:

- Ruff linting
- Black formatting
- mypy static type checks
- coverage-enforced pytest
- pre-commit hooks
- architecture contract tests
- documentation validation in test suite

## Near-Term Platform Services

- Scheduler
- Project Memory
- Plugin SDK
- Agent Framework
