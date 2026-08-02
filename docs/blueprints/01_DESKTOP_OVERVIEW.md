# Atlas Blueprint 01: Desktop Overview

## Purpose

Define the complete Atlas desktop shell blueprint as an implementation-ready interaction architecture reference.

This blueprint describes shell composition and responsibilities without redefining product architecture.

## Primary Users

- Solo builders
- Creative professionals
- Product and engineering teams
- Enterprise operators

## Governing References

- PRODUCT_BIBLE.md
- UX_SPECIFICATION.md
- DESKTOP_SHELL_V1.md
- ACTIVITY_MODEL.md
- COMMAND_SYSTEM.md
- STUDIO_TAXONOMY.md
- UNIVERSAL_SEARCH.md
- LONG_SESSION_UX.md
- ENTERPRISE_SHELL.md

## ASCII Layout

```text
+---------------------------------------------------------------------------------------------------+
| TOP BAR                                                                                           |
| [Org/Tenant] [Space] [Project] [Studio] [Global Search Entry] [Command Entry] [Mission Control] |
+------------------------------+----------------------------------------------------+---------------+
| SIDEBAR                      | WORKSPACE REGION                                   | INSPECTOR     |
| - Core Destinations          | - Context Header                                   | - Properties  |
| - Studio Navigation          | - Tabs / Splits / Views                            | - Metadata    |
| - Favorites / Pins / Recent  | - Active Canvas or Document Surface                | - History     |
| - Enterprise Scope Markers   | - Local Activity Anchors                           | - AI Signals  |
+------------------------------+----------------------------------------------------+---------------+
| BACKGROUND TASK STRIP: active jobs, blocked jobs, retry/cancel controls (in-scope)              |
+---------------------------------------------------------------------------------------------------+
| STATUS BAR: Workspace | Models | GPU | Cloud | Git | Sync | Memory | Jobs | Notifications        |
+---------------------------------------------------------------------------------------------------+

Overlay Layers (top to bottom):
1) Mission Control
2) Command Palette / Search / Quick Switcher surfaces
3) Notification stack
4) Activity Center panel
```

## Components

- Top Bar
- Sidebar
- Workspace region
- Inspector
- Background Task Strip
- Status Bar
- Activity Center surface
- Notification layer
- Command/Search/Quick-switch surfaces
- Mission Control entry surface

## Regions, Ownership, and Responsibilities

### Top Bar

Purpose:

- global context identity and entry points

Ownership:

- Shell navigation system

Responsibilities:

- show scope (tenant, space, project, studio)
- expose Mission Control and command/search entry points

Visibility rules:

- always visible in standard mode
- reduced but persistent in deep-focus mode

### Sidebar

Purpose:

- structural navigation and studio discovery

Ownership:

- Studio taxonomy projection layer

Responsibilities:

- provide deterministic pathways to projects/studios/assets/research/settings
- show pinned, favorite, recent access groups

Visibility rules:

- can collapse by mode and window width
- primary destinations remain reachable via keyboard regardless of collapsed state

### Workspace

Purpose:

- primary production surface

Ownership:

- active workspace session

Responsibilities:

- host task-specific views and split contexts
- preserve context continuity through project/studio/view transitions

Visibility rules:

- always present
- receives highest layout priority

### Inspector

Purpose:

- precision detail and property controls

Ownership:

- inspector controller with object-bound context

Responsibilities:

- surface properties, metadata, lineage, AI suggestions
- support follow, lock, and compare behavior

Visibility rules:

- docked or detached
- collapsible in focus modes

### Status Bar

Purpose:

- ambient shell telemetry only

Ownership:

- status projection from activity/system state

Responsibilities:

- summarize health and active state
- deep-link to detail surfaces

Visibility rules:

- always visible unless explicit presentation mode policy hides low-priority items

### Activity Center

Purpose:

- canonical execution history projection

Ownership:

- activity model projection

Responsibilities:

- timeline, filters, retries, diagnostics entry

Visibility rules:

- on-demand panel/detached view
- not required to be permanently visible

### Notification Layer

Purpose:

- escalation and decision routing

Ownership:

- activity escalation policy

Responsibilities:

- deliver warning and critical attention cues

Visibility rules:

- mode-aware suppression and grouping
- persistent for critical until acknowledged

## Navigation

- Structural navigation: Sidebar and Top Bar scope selectors
- Retrieval navigation: Universal Search
- Execution navigation: Command Palette
- Context jump navigation: Quick Switcher
- Macro orchestration navigation: Mission Control

## Keyboard Shortcuts

Blueprint-level behaviors:

- global shell focus cycle between Top Bar, Sidebar, Workspace, Inspector, Status
- dedicated key path for Mission Control entry
- dedicated key path for Command Palette entry
- dedicated key path for Universal Search entry
- dedicated key path for Quick Switcher entry

Note:

Exact bindings are implementation policy; semantic boundaries are governed by COMMAND_SYSTEM.md.

## Mouse Interactions

- click to select scope and destinations
- drag to resize and dock regions
- drag tabs/views for split and window extraction
- hover for contextual previews where non-critical

## AI Behaviors

- contextual suggestions in workspace and inspector
- activity-aware prompts for blocked/failed operations
- recommendation cards in home and mission views
- no autonomous high-impact action without explicit user confirmation

## Empty State

When no project or workspace is active:

- show project creation/open options
- show recent and pinned contexts
- show recommended next actions and onboarding route

## Busy State

When multiple long-running operations exist:

- active jobs in Background Task Strip
- summarized counts and severity in Status Bar
- full detail in Activity Center
- escalation to Notification Layer by policy

## Error State

When critical failures occur:

- persistent critical notification with action path
- status critical marker
- Activity Center record with remediation and history
- optionally guarded read-only state on impacted views

## Responsive Behavior

- narrow widths collapse secondary/context sidebars first
- workspace remains dominant region
- inspector collapses to drawer when needed
- command/search/quick-switcher remain keyboard-reachable regardless of layout density

## Accessibility Notes

- predictable focus order across regions
- full keyboard access to all shell entry points
- non-color indicators for severity and status
- motion-reduced behavior preserves state clarity

## Future Expansion

- plugin surfaces integrate through governed extension points
- enterprise overlays add policy and role cues without breaking region semantics
- new studios slot into taxonomy without shell restructuring
- mission and command layers scale through scope and ranking controls