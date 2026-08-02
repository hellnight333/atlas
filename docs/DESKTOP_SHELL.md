# Atlas Desktop Shell Specification

## Status Note

This document remains as foundational shell context.

Authoritative shell specification is in DESKTOP_SHELL_V1.md.

For Sprint 001 ambiguity resolution domains, authoritative references are:

- ACTIVITY_MODEL.md
- STUDIO_TAXONOMY.md
- UNIVERSAL_SEARCH.md
- COMMAND_SYSTEM.md
- MULTI_WINDOW_MODEL.md
- PLUGIN_GOVERNANCE.md
- LONG_SESSION_UX.md
- PERFORMANCE_TARGETS.md
- ENTERPRISE_SHELL.md

## 1. Purpose

The desktop shell is the persistent frame around all Atlas work. It provides orientation, navigation, context continuity, and operational trust while users move across studios and projects.

The shell must feel stable even when task context changes rapidly.

## 2. Shell Regions

Canonical region model:

- Top Bar
- Sidebar
- Workspace (center stage)
- Inspector (right side by default)
- Bottom Status Bar
- Overlay Surfaces (Command Palette, Search, Notifications)

## 3. Main Window

### 3.1 Structural Diagram

```text
+--------------------------------------------------------------------------------+
| TOP BAR: Space | Project | Studio | Global Search | Command | Profile          |
+---------------------------+------------------------------------+----------------+
| SIDEBAR                   | WORKSPACE                          | INSPECTOR      |
| - Home                    | - Tabs Row                         | - Context      |
| - Projects                | - Active Canvas/Editor/View        | - Properties   |
| - Assets                  | - Inline Panels                    | - Diagnostics  |
| - Research                | - Activity Anchors                 | - History      |
| - Publishing              |                                    |                |
+---------------------------+------------------------------------+----------------+
| STATUS BAR: mode | task state | sync | agent activity | alerts | shortcuts hint |
+--------------------------------------------------------------------------------+
```

### 3.2 Behavior

- The shell frame remains visually stable across screens.
- Region resize is direct-manipulation with snap points.
- User-customized shell layout persists per workspace layout profile.

## 4. Top Bar

### 4.1 Responsibilities

- global orientation (Space, Project, Studio)
- global actions (Search, Command Palette, Quick Create)
- account and collaboration state

### 4.2 Required Elements

- Space selector
- Project selector
- Studio indicator and quick switcher
- Global search entry
- Command palette trigger
- Presence and account controls

### 4.3 Design Rules

- no dense secondary controls in top bar
- high-frequency commands discoverable via keyboard
- breadcrumbs are visible when deep in a workflow

## 5. Sidebar

### 5.1 Purpose

Persistent navigation across major product surfaces.

### 5.2 Navigation Sections

- Core: Home, Projects, Activity
- Production: Assets, Research, Video, Image, Publishing
- Intelligence: Agents, Memory, Logs
- Platform: Marketplace, Settings

### 5.3 Behavior

- collapsible width (icon-only, compact, expanded)
- pin frequently used destinations
- per-user ordering allowed within section constraints

## 6. Workspace Region

### 6.1 Role

Primary execution surface for the current task.

### 6.2 Capabilities

- tabbed documents/views
- split panes (horizontal and vertical)
- embedded timeline and activity overlays
- context-specific canvases (flow map, board, editor, preview)

### 6.3 Workspace Rules

- one active focus target at a time
- context switches preserve scroll/selection state
- long-running operations show non-blocking inline progress

## 7. Inspector

### 7.1 Purpose

High-density contextual detail, properties, diagnostics, and related history.

### 7.2 Default Sections

- summary
- properties
- dependencies
- history
- quality checks

### 7.3 Behavior

- content adapts to active object (asset, step, workflow, publish target)
- can be detached into a second window
- optional auto-hide in distraction-minimized mode

## 8. Bottom Status Bar

### 8.1 Purpose

Provide always-available operational awareness without visual noise.

### 8.2 Information Strata

- workspace mode (Explore, Build, Resolve)
- active job and queue status
- sync and persistence health
- agent activity and confidence indicators
- warnings and blockers

### 8.3 Rules

- status bar is never the only place critical failures appear
- warning severity uses both color and shape/icon encoding
- click-through opens relevant activity details

## 9. Docking Rules

### 9.1 Dock Targets

- left rail
- center workspace
- right inspector rail
- bottom drawer
- floating window

### 9.2 Snap System

```text
[Left Rail][Center 70%][Right Rail]
            [Bottom Drawer Optional]
```

- snap guides appear during drag
- minimum readable widths enforced
- panel cannot be docked into invalid zones

### 9.3 Persistence

- layout saved per workspace template
- temporary "session override" possible without altering template defaults

## 10. Tabs

### 10.1 Tab Types

- content tabs (assets, docs, previews)
- utility tabs (activity, diagnostics)
- pinned tabs (high-priority persistent)

### 10.2 Interaction Rules

- reorder by drag
- pin/unpin
- split tab to adjacent pane
- duplicate view when comparative review is needed

### 10.3 Safety and Recovery

- unsaved changes indicator
- close-confirm when destructive context loss risk exists
- recently closed tab recall via command system

## 11. Search System

### 11.1 Search Scopes

- global (spaces/projects/studios/assets)
- local (current project)
- contextual (current screen object types)

### 11.2 Search UX Behavior

- instant ranked results
- scope chips visible and editable
- keyboard navigation first-class
- previews available before navigation

## 12. Command Palette

### 12.1 Entry

- keyboard shortcut
- top bar trigger

### 12.2 Capabilities

- command execution
- natural-language intent parsing
- recent command history
- context suggestions

### 12.3 States

- global mode
- studio mode
- object mode (asset selected, workflow step selected, etc.)

Detailed command behavior is defined in COMMAND_PALETTE.md.

## 13. Notifications

### 13.1 Notification Classes

- informational
- success
- warning
- blocker

### 13.2 Delivery Channels

- toast (ephemeral, low severity)
- inbox panel (persistent list)
- status bar badge (summary)
- modal interrupt (high-severity confirmation/blocker only)

### 13.3 Attention Policy

- grouped by workflow context
- rate-limited by mode
- never interrupt active text input unless blocker class

## 14. Multi-Monitor Behavior

### 14.1 Display Strategy

- monitor A: primary workspace
- monitor B: inspector/activity/timeline or alternate studio view

### 14.2 Window Coordination

- linked focus option: selecting object in one window updates inspector in another
- independent focus option: separate tasks without cross-update

### 14.3 Continuity

- restore previous multi-monitor layout on relaunch
- fallback safely if monitor unavailable

## 15. Shell Modes

### 15.1 Focus Mode

- minimized chrome
- hidden low-priority navigation
- status essentials only

### 15.2 Review Mode

- split compare-friendly layout defaults
- history and diagnostics surfaced

### 15.3 Presentation Mode

- clean display for stakeholder walkthroughs
- controlled overlays only

## 16. Shell Quality Criteria

The shell is successful when users can:

- always answer "where am I?"
- always answer "what is happening now?"
- always recover from layout or navigation errors
- operate quickly without pointer-heavy interaction
- maintain focus during long production sessions