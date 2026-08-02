# Atlas Long-Session UX

## 1. Purpose

This document defines shell behavior for sustained professional work sessions (8 to 10 hours).

It resolves fatigue, interruption, and continuity gaps in long-duration usage.

This is the source of truth for long-session UX policy.

## 2. Long-Session Design Principles

1. Attention is a constrained resource.
2. Friction accumulates non-linearly over time.
3. Recovery speed is as important as task speed.
4. Interface should adapt to context without becoming unpredictable.
5. Notification value must exceed interruption cost.

## 3. Attention Management Model

### 3.1 Attention Modes

- `explore`
- `build`
- `resolve`
- `deep_focus`

Mode can be user-selected or context-suggested.

### 3.2 Attention Budget

Shell enforces attention budget rules by reducing low-value interruption volume over session duration.

Budget levers:

- notification frequency caps
- non-critical animation suppression
- background event bundling
- deferred suggestion batching

## 4. Fatigue Reduction Policies

### 4.1 Visual Fatigue

- reduce persistent high-contrast accent usage over long sessions
- prevent dense telemetry overpopulation in primary workspace

### 4.2 Cognitive Fatigue

- collapse non-essential panels in deep-focus mode
- compress repetitive status updates into grouped summaries

### 4.3 Decision Fatigue

- avoid prompting for low-impact confirmations repeatedly
- provide reversible defaults where safe

## 5. Focus Mode Architecture

Focus mode behavior:

- hide non-critical chrome layers
- preserve only active task context, status essentials, and urgent alerts
- lock optional side surfaces behind explicit reveal action

Focus mode is reversible with one action and restores prior layout state.

## 6. Adaptive UI Behavior

Adaptive rules:

- adapt density and interruption posture based on mode and session phase
- never relocate core navigation anchors automatically
- all adaptive changes must be visible and reversible

Adaptation cannot alter semantic meaning of controls.

## 7. Notification Suppression

Suppression model:

- suppress low-severity repeated events during deep-focus
- aggregate medium-severity events into periodic digest cards
- preserve immediate delivery of critical events

Suppressed events remain available in Activity Center and Notification inbox.

## 8. Recovery After Interruption

### 8.1 Interruption Recovery Pack

After interruption, shell offers:

- "where you were" state snapshot
- unfinished tasks list
- unresolved decisions list
- suggested next action

### 8.2 Recovery Priority Rules

1. restore cursor and active object focus
2. restore visible context dependencies
3. restore activity details for interrupted operations

## 9. Session Continuity

Continuity contract:

- preserve intent-relevant context across breaks and relaunches
- maintain lightweight timeline of major actions and transitions
- prevent silent loss of temporary but user-significant state

## 10. Long-Session Telemetry Surfaces

Allowed long-session ambient signals:

- active mode
- background workload summary
- unresolved critical events count

Disallowed persistent signals:

- repetitive low-value progress ticks
- non-actionable activity noise

## 11. Anti-Ambiguity Rules

1. Focus mode must not hide critical risk indicators.
2. Suppressed notifications must remain recoverable.
3. Adaptive UI cannot change command semantics.
4. Recovery context must be one step away after interruption.
5. Long-session policies apply consistently across windows and monitors.

## 12. Cross-References

- Activity escalation and suppression routing: ACTIVITY_MODEL.md
- Shell integration points: DESKTOP_SHELL_V1.md
- Performance constraints for adaptive behavior: PERFORMANCE_TARGETS.md
- Multi-window continuity: MULTI_WINDOW_MODEL.md