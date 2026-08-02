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

## Governance Gate

Runtime execution requested -> Approval gate -> (WAITING_APPROVAL | proceed)

Nothing in Atlas is autonomous. When a declarative policy matches, the runtime pauses before a
job exists and waits for a human decision. See `APPROVAL_SYSTEM.md`.

## Distributed Execution Path

Approval gate -> Placement gate -> Reservation -> Lease -> Worker -> Provider -> Asset

Execution location is a scheduling decision, never a user decision. Work is created only once a
worker slot is reserved, and every terminal path returns the slot. See
`DISTRIBUTED_RUNTIME.md`.

## Governance Scopes

Organization -> Workspace -> Project -> Object

Permissions resolve from role data, never from a role-name branch. Policies inherit downward
with locked keys that a narrower scope cannot override. Audit is append-only, and a worker
belongs to one organization or the shared pool. See `ENTERPRISE_GOVERNANCE.md`.

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
