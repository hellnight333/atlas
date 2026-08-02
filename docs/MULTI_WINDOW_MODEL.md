# Atlas Multi-Window Conflict Model

## 1. Purpose

This document defines authoritative behavior for multi-window and multi-monitor operations, including conflict detection, authority rules, and recovery.

This is the source of truth for window ownership and concurrent edit semantics.

## 2. Scope

Applies to:

- multiple windows in one session
- detached inspectors and viewers
- synchronized and independent window modes
- cross-monitor window orchestration

## 3. Ownership Model

### 3.1 Ownership Types

- View Ownership: which window currently controls active view state
- Edit Ownership: which window has write-intent priority for an object
- Selection Ownership: which window drives shared selection in sync mode

### 3.2 Ownership Indicators

Each window must show:

- current mode (synchronized or independent)
- write-intent status for active object
- sync scope toggles

## 4. Concurrent Editing Model

### 4.1 Edit States

- `unlocked`
- `soft_locked`
- `edit_in_progress`
- `read_only_guarded`
- `conflict_detected`

### 4.2 Locking Semantics

- Soft lock: advisory ownership with override pathway
- Guarded read-only: enforced when policy or active high-risk operation requires single authority

### 4.3 Conflict Classes

1. Parallel field edits on same object
2. Structural edits plus stale view edits
3. Cross-window mode mismatch (independent vs synchronized assumptions)
4. Detached inspector stale-binding conflicts

## 5. Window Authority Modes

### 5.1 Synchronized Mode

- shared project/studio context
- selectable sync dimensions: selection, filters, inspector, timeline focus

### 5.2 Semi-Synchronized Mode

- shared project context, independent view contexts
- limited synchronization of selected dimensions

### 5.3 Independent Mode

- each window manages its own context state
- explicit indicators required to avoid accidental assumptions

## 6. Detached Inspector and Viewer Rules

### 6.1 Detached Inspector

- can be `follow` or `locked`
- when locked, must show stale-state warning if source object changes elsewhere

### 6.2 Detached Viewer

- read-optimized by default
- write actions require explicit context authority handoff

## 7. Read-Only States

Read-only triggers:

- policy constraints
- active authoritative edit in another window
- unresolved synchronization conflict
- stale state beyond freshness threshold

Read-only states must include:

- reason
- current authority holder
- path to regain write authority

## 8. Conflict Indicators

Conflict signal levels:

- Local hint: inline marker near affected object
- Window banner: when edit authority is ambiguous
- Global alert: when conflict risks data integrity

All indicators must provide one-step access to resolution flow.

## 9. Recovery Model

Recovery options:

- accept external authoritative version
- merge own edits into latest
- duplicate as alternate branch
- retry write after sync refresh

Recovery records must be added to Activity timeline.

## 10. Cross-Monitor Synchronization

Rules:

- monitor arrangement changes must not silently drop window authority metadata
- restored windows must re-evaluate sync mode on topology change
- unresolved conflicts persist visibly after monitor reconnection

## 11. Anti-Ambiguity Rules

1. No invisible authority transfer between windows.
2. Detached windows cannot silently mutate project-critical state.
3. Conflict state must be explicit before commit.
4. Read-only state must always explain cause and resolution path.
5. Sync mode must be visible in window chrome at all times.

## 12. Cross-References

- Shell window hierarchy: DESKTOP_SHELL_V1.md
- Activity and error propagation: ACTIVITY_MODEL.md
- Command boundaries for cross-window actions: COMMAND_SYSTEM.md
- Enterprise role constraints: ENTERPRISE_SHELL.md