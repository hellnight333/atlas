# Atlas Desktop Shell Specification v1.0

## Document Status

- Version: 1.0
- Scope: Atlas desktop shell architecture and UX behavior
- Type: Product specification (implementation-neutral)
- Dependencies: PRODUCT_BIBLE.md, UX_SPECIFICATION.md, INFORMATION_ARCHITECTURE.md, DESIGN_SYSTEM.md

## Intent

This specification defines the complete Atlas desktop environment as a coherent, scalable workspace system for professional creation and execution.

It does not define implementation technology.

It does not redefine backend architecture.

It does not replace existing Atlas product foundations.

## Normative References (Single Source of Truth)

This shell specification delegates detailed behavior in the following domains to authoritative companion documents:

- ACTIVITY_MODEL.md
- STUDIO_TAXONOMY.md
- UNIVERSAL_SEARCH.md
- COMMAND_SYSTEM.md
- MULTI_WINDOW_MODEL.md
- PLUGIN_GOVERNANCE.md
- LONG_SESSION_UX.md
- PERFORMANCE_TARGETS.md
- ENTERPRISE_SHELL.md

When this document and a delegated document appear to overlap, the delegated document is authoritative for that domain.

---

## Chapter 1: Design Philosophy

### 1.1 Why Atlas Uses a Desktop Metaphor

Atlas is a sustained-work product, not a single-task utility. A desktop metaphor is used because professionals need:

- persistent spatial memory
- durable context continuity
- simultaneous access to multiple work surfaces
- deliberate control over attention

Rationale:

A document-first or page-first metaphor fragments context and forces repeated reorientation. The desktop metaphor enables users to build stable work environments that compound over time.

### 1.2 Why Creators Need Persistent Workspaces

Creative and strategic work is non-linear. Users frequently move between exploration, production, and review without finishing one stage before touching the next.

Persistent workspaces allow users to preserve:

- open references
- active comparisons
- unresolved decisions
- in-progress assets

Rationale:

Reconstructing setup costs cognitive energy and destroys momentum. Persistent workspaces reduce restart friction and preserve decision quality.

### 1.3 Why Context Is More Important Than Screens

In Atlas, context is the primary unit of continuity. Screens are only views into context.

Context includes:

- active Space and Project
- Studio mode
- selected workflow stage
- active assets
- decision history
- background operations

Rationale:

If context is stable, users can tolerate view changes. If context is lost, even familiar screens feel disorienting.

### 1.4 Why Navigation Should Disappear into the Background

Navigation must be present but quiet. Atlas prioritizes doing over browsing.

Principles:

- navigation should be predictable
- high-frequency routes should be one-step or commandable
- users should not navigate just to check system state

Rationale:

In expert workflows, visible but unobtrusive wayfinding improves flow. Navigation that demands attention becomes a productivity tax.

---

## Chapter 2: Window Hierarchy

### 2.1 Window Taxonomy

Atlas defines nine window classes.

1. Main Window
2. Workspace Window
3. Floating Panels
4. Modal Dialogs
5. Transient Windows
6. Secondary Windows
7. Popups
8. Context Windows
9. Inspector Windows

### 2.2 Hierarchy and Z-Order

```text
Level 0: Main Window / Secondary Windows (independent roots)
Level 1: Workspace Windows (inside each root)
Level 2: Docked/Floating Panels
Level 3: Context Windows / Popups / Transient Windows
Level 4: Modal Dialogs (blocking scope-defined regions)
```

Rationale:

A strict hierarchy avoids unpredictable focus behavior and ensures users can always reason about which surface is authoritative.

### 2.3 Main Window

Definition:

- the primary application root for a user session

Responsibilities:

- global shell frame
- top-level navigation
- project/studio identity
- activity and status awareness

Rationale:

The main window anchors orientation and remains stable across workflow transitions.

### 2.4 Workspace Window

Definition:

- the active production surface inside a project context

Responsibilities:

- tabbed work views
- split panes
- active editing and review surfaces

Rationale:

Separating workspace from global frame allows local complexity without destabilizing global orientation.

### 2.5 Floating Panels

Definition:

- detachable, non-blocking utility surfaces

Examples:

- detached inspector
- compare viewer
- timeline detail panel

Rules:

- always tethered to a parent workspace context
- must advertise source project and studio

Rationale:

Floating panels support expert multitasking while preventing context ambiguity.

### 2.6 Modal Dialogs

Definition:

- blocking surfaces for high-impact decisions or required inputs

Rules:

- modal scope must be explicit: object-level, workspace-level, or project-level
- low-priority information never uses modal patterns
- all modals require clear consequence language

Rationale:

Modal interruption is costly and should only occur when user intent or data integrity requires explicit confirmation.

### 2.7 Transient Windows

Definition:

- short-lived surfaces for previews, inline picks, and quick inspections

Rules:

- auto-dismiss on context loss unless pinned
- no critical actions as transient-only affordances

Rationale:

Transient windows accelerate exploration but must not become hidden dependencies.

### 2.8 Secondary Windows

Definition:

- additional root windows for multi-tasking or multi-monitor workflows

Modes:

- linked (synchronized context)
- independent (same account, distinct active context)

Rationale:

Secondary windows increase throughput for advanced users, especially for compare/monitor workflows.

### 2.9 Popup Rules

Popup constraints:

- popups never contain irreversible primary actions
- popups must close predictably via keyboard and pointer
- popup origin must remain visually apparent

Rationale:

Popups are interaction accelerators, not decision hubs.

### 2.10 Context Windows

Definition:

- lightweight windows bound to a selected object or workflow node

Use:

- deep metadata inspection
- object-centric shortcuts
- contextual explainability details

Rationale:

Context windows reduce navigation detours for high-frequency inspection tasks.

### 2.11 Inspector Windows

Definition:

- dedicated property and diagnostic surfaces detached from the main inspector rail

Rules:

- single-object focus by default
- optional lock mode to prevent selection-driven changes

Rationale:

Inspector detachment supports side-by-side evaluation and expert parallel operations.

---

## Chapter 3: Desktop Layout

### 3.0 Authority Boundary

Region definitions in this chapter describe shell composition.

Execution-state ownership and propagation are authoritative in ACTIVITY_MODEL.md.

Long-session adaptation behavior is authoritative in LONG_SESSION_UX.md.

### 3.1 Canonical Shell Regions

Atlas shell includes the following persistent and layered regions:

- Top Bar
- Left Sidebar
- Workspace Canvas
- Right Inspector
- Bottom Status Bar
- Background Task Area
- Activity Center
- Notification Layer
- Overlay Layer
- Command Palette Layer

### 3.2 Canonical Layout Diagram

```text
+----------------------------------------------------------------------------------+
| TOP BAR: Space | Project | Studio | Global Search | Command | Presence          |
+--------------------------+-----------------------------------+-------------------+
| LEFT SIDEBAR             | WORKSPACE CANVAS                 | RIGHT INSPECTOR   |
| Core + Studio Nav        | Tabs / Splits / Canvas / Editors | Properties/History|
| Pins + Favorites         | Inline views and previews         | Metadata/AI hints |
+--------------------------+-----------------------------------+-------------------+
| BACKGROUND TASK AREA (collapsible strip + quick progress controls)              |
+----------------------------------------------------------------------------------+
| STATUS BAR: workspace | model | jobs | sync | memory | git | cloud | alerts      |
+----------------------------------------------------------------------------------+

Layered Overlays:
- Notification Layer (non-modal)
- Activity Center (slide-over or detached)
- Overlay Layer (search, quick pickers, context tools)
- Command Palette Layer (highest non-critical interactive layer)
```

### 3.3 Region Specifications and Rationale

#### Top Bar

Purpose:

- global orientation and fast access to universal commands

Rationale:

Global identity and command entry should remain stable regardless of local workspace complexity.

#### Left Sidebar

Purpose:

- persistent structural navigation and studio switching

Rationale:

A stable left anchor reinforces spatial memory and reduces retrieval time for high-level destinations.

#### Workspace Canvas

Purpose:

- primary production environment for active work

Rationale:

Creative throughput depends on maximizing useful central space while preserving context controls at edges.

#### Right Inspector

Purpose:

- contextual detail, properties, lineage, and recommendations

Rationale:

Keeping detail to the side preserves forward production flow while supporting precision decisions.

#### Bottom Status Bar

Purpose:

- always-available operational awareness

Rationale:

Professionals require ambient telemetry without leaving the task surface.

#### Background Task Area

Purpose:

- monitor and control long-running operations without modal interruption

Rationale:

Background processes must stay visible enough to preserve trust while not hijacking attention.

#### Activity Center

Purpose:

- chronological command, workflow, and agent activity trace

Rationale:

A unified activity narrative supports debugging, auditing, and retrospective learning.

#### Notification Layer

Purpose:

- deliver prioritized feedback and action prompts

Rationale:

Feedback must be timely yet mode-sensitive to avoid flow disruption.

#### Overlay Layer

Purpose:

- temporary interaction surfaces (quick search, pickers, object actions)

Rationale:

Overlays minimize navigation overhead for localized tasks.

#### Command Palette Layer

Purpose:

- universal keyboard-first control plane

Rationale:

The command layer turns shell complexity into a fast, composable interaction system.

---

## Chapter 4: Navigation

### 4.0 Authority Boundary

Navigation principles in this chapter define shell movement behavior.

Studio structure, scaling, and discovery are authoritative in STUDIO_TAXONOMY.md.

Search behavior is authoritative in UNIVERSAL_SEARCH.md.

System boundary between Search, Command Palette, Quick Switcher, and Mission Control is authoritative in COMMAND_SYSTEM.md.

### 4.1 Navigation Principles

1. Orientation before motion
2. Lowest-friction path for high-frequency actions
3. Context-preserving transitions
4. Command parity for all major navigation actions
5. Reversible movement and history visibility

### 4.2 Project Navigation Rules

- project switch always displays target context summary before commit
- unsaved/high-risk transitions require explicit confirmation
- users can open project in current workspace or new window

Rationale:

Project switches are high-context transitions; users need confidence before commitment.

### 4.3 Studio Navigation Rules

- studio switch preserves active project scope
- related assets remain discoverable across studio changes
- unresolved blockers persist as visible badges

Rationale:

Studios are lenses into one project, not separate silos.

### 4.4 Asset Navigation Rules

- asset access supports list, recent, pinned, and relation-driven pathways
- opening an asset should preserve backtrace to source flow context

Rationale:

Asset navigation must support both retrieval and situational understanding.

### 4.5 History Navigation Rules

- history captures navigation and action context
- users can traverse view history without mutating project state

Rationale:

History should function as cognitive recovery, not only undo mechanics.

### 4.6 Search Navigation Rules

- search supports direct-jump and preview modes
- results expose object type, scope, and relationship hints

Rationale:

Search should reduce exploration effort while maintaining confidence in destination relevance.

### 4.7 Recent, Pinned, and Favorites

Recent:

- auto-generated by recency and frequency

Pinned:

- explicit user commitments for active focus entities

Favorites:

- durable, user-curated high-value references

Rationale:

These layers map to different memory strategies: automatic recall, active commitment, and long-term value.

### 4.8 Keyboard Navigation

Rules:

- all primary destinations reachable without pointer
- predictable focus traversal across shell regions
- command-based direct jumps for projects, studios, and assets

Rationale:

Keyboard navigation is foundational for expert throughput and accessibility.

### 4.9 Mouse Navigation

Rules:

- pointer actions prioritize discoverability and precision
- drag interactions expose valid drop targets and outcomes

Rationale:

Mouse interactions should remain explicit and confidence-preserving.

### 4.10 Trackpad Navigation

Rules:

- gestures map to non-destructive navigation and view control
- no gesture-only critical actions

Rationale:

Trackpad support increases fluidity while requiring clear fallback parity.

---

## Chapter 5: Workspace Engine

### 5.1 Entity Definitions

Workspace:

- active arrangement of views and context in a project

Project:

- bounded objective container of workflows, assets, and decisions

Session:

- time-bound run of user activity and background state

View:

- a visible representation of an object or workflow state

Layout:

- structural arrangement blueprint of panes and panels

Template:

- reusable starter definition for workspace + flow posture

### 5.2 Persistence Model

Persisted elements:

- active project/studio
- open tabs and split structure
- panel visibility and sizes
- inspector locks and filters
- status of background task surfaces

Non-persisted by default:

- transient popups
- ephemeral hover context

Rationale:

Persistence should preserve intentional setup while avoiding stale microstate clutter.

### 5.3 Workspace Restore

Restore sequence:

1. restore shell identity (space/project/studio)
2. restore layout skeleton
3. restore tab/view stack
4. reconnect background activity snapshots
5. re-surface unresolved decisions and blockers

Rationale:

Ordered restoration preserves orientation and reduces false perception of data loss.

### 5.4 Workspace Switching

Switch types:

- project switch
- layout switch
- studio switch
- window role switch

Rules:

- transition preview for high-impact switches
- preserve recoverable previous state snapshot

Rationale:

Switching should feel intentional and reversible.

### 5.5 Multiple Workspaces

Support:

- concurrent workspace instances in separate windows
- linked or independent synchronization modes

Rationale:

Complex professional tasks often require parallel contexts.

### 5.6 Saved and Temporary Layouts

Saved layouts:

- named, reusable, optionally shareable templates

Temporary layouts:

- session-scoped experiments with one-click reversion

Rationale:

Users need both durable patterns and safe experimentation.

---

## Chapter 6: Docking System

### 6.1 Dock Positions

Primary dock zones:

- left rail
- center workspace
- right rail
- bottom tray
- floating region

Diagram:

```text
+----------------+----------------------------+----------------+
| Left Dock      | Center Workspace           | Right Dock     |
| (Nav/Tools)    | (Tabs/Splits/Canvas)       | (Inspector)    |
+----------------+----------------------------+----------------+
| Bottom Dock (Tasks/Logs/Activity/Terminal-like utility surfaces)               |
+------------------------------------------------------------------------------+
```

Rationale:

A constrained but flexible zone model preserves predictability and minimizes layout chaos.

### 6.2 Resizable Panels

Rules:

- panel resize uses clear handles and snap increments
- minimum and maximum bounds enforce usability

Rationale:

Resizable panels optimize density for task phase without breaking readability.

### 6.3 Floating Panels

Rules:

- any dockable panel can float unless policy-restricted
- floating state persists per layout profile

Rationale:

Floating behavior enables monitor-aware optimization for experts.

### 6.4 Panel Grouping

Rules:

- related utility panels can be grouped in tabbed clusters
- grouped panels share region visibility state

Rationale:

Grouping reduces chrome overhead while preserving tool depth.

### 6.5 Collapse and Restore

Rules:

- each region supports collapse with visible affordance
- restore must return previous size/position where possible

Rationale:

Collapse supports focus mode; restore supports continuity.

### 6.6 Snap Behavior

Rules:

- snap hints appear before drop commit
- invalid targets are explicitly denied
- snap tolerance tuned for precision and speed

Rationale:

Predictable snapping prevents accidental layout corruption.

### 6.7 Dock Persistence

Persisted:

- dock location
- size
- grouping
- floating coordinates (if valid at restore)

Fallback:

- if previous geometry invalid, use nearest safe region and notify user non-disruptively

Rationale:

Reliable persistence increases trust in personalized workspace setups.

---

## Chapter 7: Tab System

### 7.1 Tab Classes

- Editor tabs
- Asset tabs
- Preview tabs
- Pinned tabs
- Temporary tabs
- Split tabs
- Nested tabs (within grouped utility contexts)

### 7.2 Editor Tabs

Purpose:

- long-lived authoring and specification work

Behavior:

- preserve cursor/selection state
- unsaved indicators and conflict warnings

Rationale:

Editor tabs represent primary cognitive threads and require strong continuity.

### 7.3 Asset Tabs

Purpose:

- open reusable artifacts for inspection/editing/comparison

Rationale:

Assets are cross-workflow dependencies; tabbed access reduces navigation churn.

### 7.4 Preview Tabs

Purpose:

- quick inspection of results and references

Behavior:

- default ephemeral lifecycle until pinned or edited

Rationale:

Ephemeral previews support exploration without polluting long-term tab stacks.

### 7.5 Pinned Tabs

Purpose:

- protect critical references from accidental closure

Rationale:

Pinned tabs preserve high-value anchors during long sessions.

### 7.6 Temporary Tabs

Purpose:

- low-commitment opens from search/history lists

Rules:

- replaced by subsequent temporary open unless promoted

Rationale:

Temporary tabs keep the workspace clean during broad exploration.

### 7.7 Split Tabs

Purpose:

- side-by-side comparisons and parallel editing

Rationale:

Split views reduce cognitive load in evaluation and synthesis tasks.

### 7.8 Nested Tabs

Purpose:

- local tab sets inside grouped utility panels (activity/logs/diagnostics)

Rationale:

Nested tabs preserve tool organization without overloading primary tab lanes.

### 7.9 Tab History

Capabilities:

- recently closed recall
- tab navigation history
- open lineage from source context

Rationale:

History supports recovery and exploratory confidence.

### 7.10 Drag and Drop

Rules:

- reorder within lane
- move across split regions
- convert to new window by drag-out

Rationale:

Direct manipulation should match user mental model of workspace composition.

---

## Chapter 8: Sidebar

### 8.0 Authority Boundary

Sidebar behavior in this chapter defines shell presentation.

Studio grouping, visibility limits, enterprise policy visibility, and plugin studio classification are authoritative in STUDIO_TAXONOMY.md and ENTERPRISE_SHELL.md.

### 8.1 Sidebar Types

- Primary sidebar
- Secondary sidebar
- Context sidebar
- Studio sidebar

### 8.2 Primary Sidebar

Purpose:

- top-level destination and structural orientation

Contents:

- Home
- Projects
- Core studios and shared surfaces
- Activity and platform sections

Rationale:

Primary sidebar is the global spine of Atlas navigation.

### 8.3 Secondary Sidebar

Purpose:

- project-scoped navigation and filters

Rationale:

Secondary navigation keeps local complexity out of global destinations.

### 8.4 Context Sidebar

Purpose:

- object-related shortcuts and relationship pivots

Rationale:

Context sidebars reduce inspector overload and shorten navigation loops.

### 8.5 Studio Sidebar

Purpose:

- studio-specific workflow and artifact structure

Rationale:

Each studio requires local wayfinding without disrupting shell consistency.

### 8.6 Behavior Rules

Expansion modes:

- icon-only
- compact
- expanded

Collapse rules:

- manual collapse always available
- auto-collapse optional in focus mode

Responsive behavior:

- narrow windows prioritize primary sidebar retention
- secondary/context sidebars collapse into toggleable drawers

Rationale:

Sidebar adaptability must preserve orientation first, density second.

---

## Chapter 9: Inspector

### 9.1 Inspector Purpose

The inspector is Atlas's precision surface for understanding and modifying selected objects with full context.

Rationale:

Production surfaces favor momentum; inspector surfaces favor precision and traceability.

### 9.2 Inspector Sections

Required section model:

1. Summary
2. Property Groups
3. Metadata
4. History
5. AI Suggestions
6. Asset Details
7. Version History

### 9.3 Property Groups

Rules:

- grouped by semantic function
- advanced groups collapsed by default for beginners
- edited-but-unapplied values must be clearly marked

Rationale:

Grouping lowers cognitive load and supports fast scanning.

### 9.4 Metadata

Includes:

- origin
- ownership/context
- dependencies
- state tags

Rationale:

Metadata improves decision quality by exposing hidden relationships.

### 9.5 History and Version History

History:

- object-level change timeline and interactions

Version history:

- named snapshots, comparisons, and rollback affordances

Rationale:

Inspection without lineage undermines trust.

### 9.6 AI Suggestions in Inspector

Rules:

- suggestions are contextual and explainable
- each suggestion includes confidence and potential impact
- accept/reject feedback loops improve suggestion relevance

Rationale:

Inspector is the highest-signal location for precise recommendations.

### 9.7 Inspector Modes

- Follow mode: updates with active selection
- Lock mode: remains bound to chosen object
- Compare mode: dual-object properties and differences

Rationale:

Mode flexibility supports both reactive and analytical workflows.

---

## Chapter 10: Command Palette

### 10.0 Authority Boundary

This chapter defines command-surface posture inside the shell.

Detailed system boundaries between Command Palette, Universal Search, Quick Switcher, and Mission Control are authoritative in COMMAND_SYSTEM.md.

Search retrieval behavior and ranking are authoritative in UNIVERSAL_SEARCH.md.

### 10.1 Command Palette Role

The command palette is the primary keyboard control plane for shell and workflow operations.

Rationale:

Command-first operation reduces navigation cost and scales with expertise.

### 10.2 Core Capabilities

- natural language interpretation
- structured command invocation
- scoped execution (global/project/studio/object)
- command chaining
- contextual suggestions

Boundary rule:

- Command Palette is execution-first.
- Universal Search is retrieval-first.
- Quick Switcher is context-switch-first.
- Mission Control is workspace-orchestration-first.

### 10.3 Command Categories

1. Navigation
2. Workspace Layout
3. Studio Actions
4. Project Operations
5. Asset Operations
6. Search and Retrieval
7. Review and Quality
8. Publish and Share
9. System and Preferences

Rationale:

Categorization improves discoverability and enables predictable ranking.

### 10.4 Natural Language Behavior

Rules:

- parse intent into command candidates
- show disambiguation for low confidence
- expose "why this result" rationale

Rationale:

Natural language lowers beginner friction while preserving expert control.

### 10.5 Command History and Pins

History:

- time-ordered execution record
- optional outcome annotations

Pinned commands:

- user-curated high-frequency commands

Rationale:

Combining automatic recall with intentional pinning supports different working styles.

### 10.6 AI-Assisted Suggestions

Rules:

- suggestions derive from context and recent behavior
- never auto-execute high-impact actions
- provide opt-out and tuning controls

Rationale:

Assistance should accelerate workflow without eroding agency.

---

## Chapter 11: Search

### 11.0 Authority Boundary

This chapter defines shell-level integration points for search.

Ranking, trust model, freshness semantics, conflict handling, and latency tiers are authoritative in UNIVERSAL_SEARCH.md.

### 11.1 Universal Search Scope

Atlas universal search must index and retrieve:

- Projects
- Assets
- Studios
- Commands
- Workflows
- Memory
- Agents
- Documentation
- Settings
- History

### 11.2 Search Modes

- global
- project-scoped
- studio-scoped
- object-type filtered

Rationale:

Search needs broad coverage and precise narrowing for professional velocity.

### 11.3 Result Model

Each result includes:

- object type
- title/identifier
- scope path
- freshness or relevance signal
- preview snippet
- next actions

Result trust contract:

- every result must expose trust and freshness state per UNIVERSAL_SEARCH.md
- action pathways must prefer authoritative live state when divergence is detected

Rationale:

Users require confidence before navigation commitment.

### 11.4 Search Interaction

- keyboard-first traversal and open-in-place/new-pane options
- preview without full context switch when feasible
- recent queries and saved filters

Rationale:

Search should be both retrieval and exploratory insight surface.

---

## Chapter 12: Activity Center

### 12.0 Authority Boundary

The Activity Center is the durable timeline projection surface.

Canonical activity states, escalation logic, progress propagation, and error propagation are authoritative in ACTIVITY_MODEL.md.

### 12.1 Purpose

Activity Center is the non-modal operational timeline for everything happening in and around active work.

### 12.2 Tracked Domains

- rendering
- downloads
- uploads
- training
- research tasks
- agent execution
- notifications
- errors
- logs

Scope rule:

- Activity Center is the only canonical historical execution surface.
- Notification Layer is interruption routing only.
- Status Bar is ambient summary only.
- Background Task Area is active in-scope execution strip only.

### 12.3 Activity States

Activity state names and transitions must follow ACTIVITY_MODEL.md without local redefinition.

Rationale:

Single-state authority eliminates cross-surface inconsistency.

### 12.4 Activity Interaction

- filter by project/studio/type/severity
- jump to source object
- retry or open remediation path where applicable

Rationale:

Activity should be actionable, not a passive audit list.

### 12.5 Rendering and Heavy Tasks

Rules:

- long-running tasks always visible in task strip and activity center
- progress includes phase labels when available
- completion surfaces result links and quality checks

Rationale:

Heavy tasks are high-anxiety moments; visibility reduces uncertainty.

---

## Chapter 13: Status Bar

### 13.0 Authority Boundary

Status Bar behavior in this chapter defines ambient shell telemetry only.

Execution lifecycle state authority remains in ACTIVITY_MODEL.md.

### 13.1 Purpose

The status bar is a compact operational instrument panel.

It is never decorative.

### 13.2 Required Status Domains

- current workspace identity
- connected models
- GPU availability/usage class
- background jobs summary
- sync health
- memory context state
- Git status
- cloud connectivity

### 13.3 Interaction Rules

- each status item supports drill-down action
- warnings use visual and textual cues
- status bar avoids verbose noise; detail lives in linked surfaces

Anti-overlap rule:

- Status Bar cannot host full activity history, error diagnostics, or execution controls.

Rationale:

Professionals need ambient telemetry with one-action access to detail.

### 13.4 Priority Encoding

- normal: quiet
- caution: visible but non-blocking
- critical: highlighted with immediate pathway to resolution

Rationale:

Priority-aware encoding prevents alert fatigue.

---

## Chapter 14: Notification System

### 14.0 Authority Boundary

Notification behavior in this chapter defines interruption routing behavior.

Escalation classes and lifecycle transitions are authoritative in ACTIVITY_MODEL.md.

Long-session suppression and focus protections are authoritative in LONG_SESSION_UX.md.

### 14.1 Notification Principles

- priority-aware
- mode-aware
- action-oriented
- reversible where possible

### 14.2 Priority Levels

1. Critical
2. High
3. Standard
4. Silent

### 14.3 Delivery Behavior

Stacking:

- grouped by context and timeframe
- collapse repetitive events

Duration:

- critical persists until acknowledged
- high duration balanced by mode
- standard auto-dismiss with inbox retention
- silent logs to activity/notification center only

Progress notifications:

- must show stage and percent/range where meaningful

Persistent alerts:

- pinned in notification center and status bar badge

Undo and actions:

- reversible actions expose undo window
- actionable alerts include primary and safe secondary action

Rationale:

A notification is useful only when it supports decision and recovery.

Anti-overlap rule:

- Notification Layer must not become an activity backlog archive.

---

## Chapter 15: Multi-window

### 15.0 Authority Boundary

This chapter defines shell-level multi-window posture.

Ownership semantics, conflict classes, detached surface authority, and recovery model are authoritative in MULTI_WINDOW_MODEL.md.

### 15.1 Multi-Window Model

Atlas supports multiple simultaneous windows per user session.

Window relationship modes:

- synchronized
- semi-synchronized
- independent

Rationale:

Different workflows require different coupling levels.

### 15.2 Multiple Monitors

Rules:

- users can distribute shell regions across displays
- restore monitor-aware layouts when displays return
- fallback gracefully when display topology changes

Rationale:

Professional desks are frequently multi-monitor and should be first-class.

### 15.3 Window Synchronization

Synchronization options:

- selection sync
- project sync
- studio sync
- filter sync
- inspector sync

Rationale:

Granular synchronization avoids both duplication and unintended coupling.

Authority rule:

- sync mode and write-intent state must remain explicitly visible in every active window.

### 15.4 Shared Projects Across Windows

Rules:

- same project can be opened in multiple windows with visible sync state
- conflicting edit contexts surface clear resolution pathways

Rationale:

Parallel work requires visibility into context coherence.

### 15.5 Detached Inspectors and Viewers

Detached inspector:

- persistent precision panel on secondary display

Detached viewer:

- dedicated preview/reference surface

Rationale:

Detachment supports deep focus and reduces context switching.

---

## Chapter 16: Keyboard UX

### 16.0 Authority Boundary

Keyboard interaction in this chapter defines shell posture.

Boundary logic among Search, Command Palette, Quick Switcher, and Mission Control is authoritative in COMMAND_SYSTEM.md.

### 16.1 Keyboard-First Philosophy

Keyboard interaction is a core product posture, not a power-user add-on.

Rationale:

Keyboard-first operation improves throughput, accessibility, and flow continuity.

### 16.2 Shortcut Design Principles

- stable mnemonic logic
- conflict minimization
- discoverability via command palette and contextual hints

Rationale:

Predictable shortcut systems reduce learning friction.

### 16.3 Quick Actions

- in-context quick action invocations
- jump commands for projects/studios/assets
- focused toggles for shell regions

Rationale:

Quick actions compress high-frequency routines into minimal keystrokes.

### 16.4 Keyboard Navigation

- directional and scope-aware traversal
- region focus cycling
- tab/history motion controls

Rationale:

Keyboard users should never require pointer rescue for shell movement.

### 16.5 Command Chaining

Rules:

- users can execute command sequences with visible intermediate context
- chain steps can be saved and replayed

Rationale:

Chaining transforms repetitive operations into reusable personal workflows.

### 16.6 Power-User Workflow

Support patterns:

- command palette centricity
- pinned command sets
- window/layout switching shortcuts
- deterministic mode switching

Rationale:

Power users need sustained acceleration without losing predictability.

---

## Chapter 17: Motion

### 17.1 Motion Purpose

Motion communicates spatial relationship, causality, and state transition.

It should never be decorative noise.

### 17.2 Motion Principles

- purposeful
- brief
- predictable
- accessibility-respectful

### 17.3 Transition Families

- shell structural transitions (dock, split, collapse)
- navigation transitions (project/studio/view changes)
- feedback transitions (success/failure/progress)
- overlay transitions (search/command/activity)

Rationale:

Consistent transition families make shell behavior legible and learnable.

### 17.4 Micro-interactions

Use cases:

- focus confirmation
- snap target confirmation
- command execution acknowledgement

Rationale:

Micro-interactions provide confidence without attention theft.

### 17.5 Loading and Background Task Motion

Rules:

- loading indicators map to actual task state
- background activity motion remains subtle and persistent

Rationale:

Movement should explain system work, not mask latency.

### 17.6 AI Activity Motion

Rules:

- distinguish thinking, waiting, and completed states
- avoid anthropomorphic theatrics

Rationale:

Professional trust depends on clarity, not personality effects.

---

## Chapter 18: Performance Philosophy

### 18.0 Authority Boundary

This chapter defines performance intent and degradation philosophy.

Measurable shell targets and acceptance thresholds are authoritative in PERFORMANCE_TARGETS.md.

### 18.1 Responsiveness Principles

- acknowledge every action immediately
- preserve interaction continuity under load
- prioritize active workspace over background surfaces

Rationale:

Perceived latency directly degrades user confidence and decision quality.

### 18.2 Instant Feedback

Rules:

- immediate state change or acknowledgment on user action
- delayed operations show explicit in-progress state and expected next signal

Rationale:

Users should never wonder whether an action was received.

Measurement rule:

- all feedback and responsiveness claims must map to P50 and P95 targets in PERFORMANCE_TARGETS.md.

### 18.3 Lazy and Background Loading

Lazy loading:

- defer low-priority content until requested or likely needed

Background loading:

- prefetch likely-next context when non-disruptive

Rationale:

Balanced loading improves responsiveness without sacrificing completeness.

### 18.4 Animation Limits

Rules:

- animation never blocks input longer than necessary
- high-load conditions degrade motion complexity before degrading core interaction

Rationale:

Interaction integrity is more important than visual flourish.

### 18.5 Performance Perception Guardrails

- preserve shell frame stability during data updates
- avoid full-surface redraw semantics
- maintain readable progress signaling

Rationale:

Stable frames and truthful progress improve perceived speed and trust.

---

## Chapter 19: Future Expansion

### 19.0 Authority Boundary

Expansion posture in this chapter is constrained by the following authoritative governance documents:

- PLUGIN_GOVERNANCE.md
- STUDIO_TAXONOMY.md
- ENTERPRISE_SHELL.md

### 19.1 Expansion Philosophy

The shell is designed as a stable framework that can absorb new capabilities without structural redesign.

Rationale:

Long-term products fail when each expansion requires navigational rewrites.

### 19.2 Marketplace Support

Shell support:

- dedicated discover/manage surfaces
- compatibility and trust signals
- install impact previews

Rationale:

Ecosystem growth requires safe, transparent integration patterns.

Governance rule:

- marketplace integration must follow plugin trust levels, verification states, and containment policies in PLUGIN_GOVERNANCE.md.

### 19.3 Plugin Support

Shell support:

- extension points for panels, commands, and context actions
- containment model to prevent shell coherence drift

Rationale:

Extensibility is valuable only when bounded by consistency laws.

### 19.4 Cloud Support

Shell support:

- explicit cloud state indicators
- sync conflict visibility and remediation paths

Rationale:

Cloud behavior must be legible to preserve trust in persistence.

### 19.5 Multi-user Support

Shell support:

- presence indicators
- shared context cues
- role-aware interaction surfaces

Rationale:

Collaborative growth should augment, not destabilize, solo workflows.

Enterprise rule:

- multi-user behavior must keep tenant identity, role scope, and policy impact visible per ENTERPRISE_SHELL.md.

### 19.6 Studio Expansion

Shell support:

- studio slots that inherit common shell behavior
- studio-local navigation within global consistency boundaries

Rationale:

New studios should feel native immediately.

### 19.7 Future Atlas Products

Shell support:

- common command system
- shared workspace engine semantics
- transferable user mental model across Atlas offerings

Rationale:

A unified shell language reduces onboarding costs and supports portfolio coherence.

---

## Appendix A: Decision Traceability Matrix

The shell specification enforces the following non-negotiable outcomes:

1. Orientation continuity
2. Context integrity
3. Expert throughput
4. Reversible operations
5. Explainable assistance
6. Scalable extensibility

Additional lock outcomes introduced in Sprint 001:

7. Single authority for execution lifecycle semantics (ACTIVITY_MODEL.md)
8. Scalable studio taxonomy and discovery (STUDIO_TAXONOMY.md)
9. Trust-aware universal retrieval semantics (UNIVERSAL_SEARCH.md)
10. Explicit command-system boundary model (COMMAND_SYSTEM.md)
11. Window authority and conflict clarity (MULTI_WINDOW_MODEL.md)
12. Plugin trust and containment governance (PLUGIN_GOVERNANCE.md)
13. Long-session fatigue and focus resilience (LONG_SESSION_UX.md)
14. Measurable shell performance targets (PERFORMANCE_TARGETS.md)
15. Enterprise shell visibility and policy clarity (ENTERPRISE_SHELL.md)

Each chapter contributes directly to at least one outcome and must be preserved during implementation planning.

## Appendix B: Non-Goals

This document does not define:

- frontend framework selection
- renderer/runtime technology
- backend service architecture
- visual token implementation
- platform-specific API calls

It defines product architecture and UX behavior only.