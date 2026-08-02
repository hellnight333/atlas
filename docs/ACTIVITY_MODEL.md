# Atlas Activity Model

## 1. Purpose

This document defines the single authoritative execution lifecycle for Atlas shell activity.

It resolves responsibility overlap across:

- Status Bar
- Activity Center
- Notification Layer
- Background Task Area

This is the source of truth for activity state ownership and propagation.

## 2. Core Principles

1. Single lifecycle authority.
2. Multi-surface projection with strict role boundaries.
3. Deterministic escalation and de-escalation.
4. No silent failure states.
5. User-visible provenance for every high-impact event.

## 3. Canonical Activity Entities

### 3.1 Activity Record

A durable record representing one executable unit of work.

Required fields:

- Activity ID
- Source domain (workflow, asset, publish, agent, system)
- Scope (space, project, studio, workspace)
- State
- Severity
- Progress model
- Start timestamp
- Last update timestamp
- Completion timestamp
- Parent/child relationship (optional)
- Retry metadata (optional)

### 3.2 Activity State Machine

Canonical states:

1. `accepted`
2. `queued`
3. `running`
4. `blocked`
5. `succeeded`
6. `succeeded_with_warnings`
7. `failed_recoverable`
8. `failed_terminal`
9. `canceled`

State rules:

- Activity cannot skip directly from `accepted` to `succeeded` without at least one update event.
- Any failure state must include remediation metadata.
- `blocked` must include dependency reason and reevaluation trigger.

## 4. Source of Truth

### 4.1 Authority Layer

The **Activity Ledger** is the only authoritative state source.

The ledger is a conceptual architecture layer that owns:

- current state
- history of transitions
- error details
- progress snapshots
- escalation class

No shell surface is allowed to derive independent state.

### 4.2 Projection Rule

All shell surfaces are **read-only projections** of ledger state, with strict presentation intent.

## 5. Surface Responsibility Matrix

### 5.1 Status Bar

Role:

- ambient summary only

Displays:

- aggregate active count
- highest current severity
- sync/queue heartbeat

Must not display:

- full logs
- remediation detail

### 5.2 Background Task Area

Role:

- immediate active job strip

Displays:

- running and blocked tasks in current scope
- compact progress
- pause/cancel/retry affordances where permitted

Must not display:

- historical completed backlog beyond compact recent queue

### 5.3 Activity Center

Role:

- durable operational timeline and triage surface

Displays:

- full lifecycle history
- grouped and filterable records
- remediation workflows
- retry lineage

Must not display:

- transient decorative alerts with no action impact

### 5.4 Notification Layer

Role:

- interruption channel for escalation events

Displays:

- state changes that require awareness or decision
- reversible action confirmations

Must not display:

- routine state ticks
- low-value progress noise

## 6. Escalation Model

### 6.1 Severity Classes

- `info`
- `attention`
- `warning`
- `critical`

### 6.2 Escalation Triggers

Escalation occurs when:

- activity enters `failed_terminal`
- recoverable failure retries exceed policy threshold
- running duration exceeds SLA class threshold
- dependent chain enters blocked cascade

### 6.3 Surface Escalation Routing

- `info`: Status Bar + Activity Center
- `attention`: Background Task Area + Activity Center
- `warning`: Notification Layer + Background Task Area + Activity Center
- `critical`: Notification Layer (persistent) + Status Bar critical marker + Activity Center

### 6.4 De-escalation

Alerts are de-escalated only when:

- user acknowledges
- system resolves and records stable completion
- fallback action chosen and applied

## 7. Progress Propagation

### 7.1 Progress Types

- Percent progress (deterministic)
- Stage progress (multi-phase)
- Indeterminate progress (heartbeat only)

### 7.2 Propagation Rules

- Source updates ledger.
- Ledger snapshots are pushed to projections.
- Projection refresh cadence is bounded by mode and task criticality.

No surface can synthesize progress not present in ledger.

## 8. Error Propagation

### 8.1 Error Record Requirements

Every failure transition must include:

- error class
- user impact class
- scope of impact
- immediate next step
- optional automated recovery path

### 8.2 Error Visibility

- Status Bar: severity marker only
- Background Task Area: active failure card
- Activity Center: full diagnostics and timeline
- Notification Layer: concise impact + action CTA

## 9. Long-Running Job Behavior

A job is classified long-running when it exceeds its class baseline threshold.

Long-running policy:

- pin in Background Task Area while active
- include elapsed time and phase
- auto-route to Activity Center details for expanded diagnostics
- emit attention-level notification only once per threshold crossing

## 10. Background Task Visibility

Visibility priorities:

1. In-scope active tasks (always visible in task strip)
2. In-scope blocked tasks (always visible until resolved)
3. Out-of-scope critical tasks (status marker + notification)
4. Completed tasks (Activity Center history)

## 11. Ownership Model

Ownership hierarchy:

- State Ownership: Activity Ledger
- Projection Ownership: Shell surface controllers
- Escalation Ownership: Activity policy rules
- Recovery Ownership: user + policy-constrained actions

## 12. Anti-Ambiguity Rules

1. A surface cannot introduce a state label not in the canonical state machine.
2. A surface cannot suppress `critical` events.
3. Activity Center is the only canonical historical view.
4. Notification Layer cannot become a backlog archive.
5. Status Bar cannot become an execution console.

## 13. Cross-References

- Shell integration: DESKTOP_SHELL_V1.md
- Long-session interaction: LONG_SESSION_UX.md
- Performance thresholds for activity updates: PERFORMANCE_TARGETS.md
- Enterprise visibility overlays: ENTERPRISE_SHELL.md