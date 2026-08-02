# Atlas Workspace System Specification

## Status Note

This document defines workspace composition and continuity behavior.

Authoritative multi-window ownership, conflict detection, read-only safeguards, and recovery semantics are defined in MULTI_WINDOW_MODEL.md.

Authoritative long-session behavior constraints are defined in LONG_SESSION_UX.md.

## 1. Purpose

The workspace system defines how users arrange, persist, and switch their working environment across tasks, studios, projects, windows, and monitors.

It is the operational backbone for high-throughput professional work.

## 2. Concept Model

Core entities:

- Space: organizational umbrella
- Project: bounded objective domain
- Workspace: active arrangement and context state inside a project
- Layout: spatial arrangement preset
- Template: reusable workspace+flow starting model

## 3. Spaces

### 3.1 Purpose

Spaces separate major domains of work while preserving coherent identity and standards.

### 3.2 Behavior

- each space can contain multiple projects
- defaults for studios, templates, and quality bars can vary by space
- users can switch spaces without losing open project state

### 3.3 Space Types

- Personal Space
- Team Space
- Client Space
- Experimental Space

## 4. Projects

### 4.1 Project as Workspace Container

Each project contains:

- project-level assets
- project-level activity
- available studios
- workspace layouts
- decision history

### 4.2 Project Working States

- Active
- Paused
- Archived
- Handed Off

Project state influences default workspace and notification posture.

## 5. Docking System

### 5.1 Docking Zones

- left navigation rail
- center task region
- right inspection rail
- bottom utility drawer
- floating detached window

### 5.2 Docking Rules

- any dockable panel advertises valid drop zones
- invalid drop zones are visually blocked
- minimum sizes preserve readability and control usability

### 5.3 Adaptive Docking

- workspace can suggest optimized layouts based on active studio and task stage
- suggestions are optional and reversible

## 6. Saved Layouts

### 6.1 Layout Types

- Personal default layout
- Studio-specific layout
- Task-mode layout (Explore, Build, Resolve)
- Presentation layout

### 6.2 Save Behavior

- manual save as named layout
- optional auto-save on session close
- snapshot history for recovery

### 6.3 Layout Portability

- layouts can be copied across projects in same space
- team spaces can publish shared canonical layouts

## 7. Workspace Templates

### 7.1 Purpose

Templates accelerate project startup with opinionated but editable structure.

### 7.2 Template Contents

- default shell layout
- studio sequence suggestions
- starter asset folders
- default workflow cards
- baseline decision checkpoints

### 7.3 Template Governance

- templates versioned with changelog notes
- deprecation policy for outdated templates
- migration prompts for existing projects (opt-in)

## 8. Studio Switching

### 8.1 Philosophy

Switching studios should feel like changing lenses, not changing products.

### 8.2 Behavior

- studio switch preserves project context and selected relevant assets
- panel continuity keeps user orientation stable
- recent-studio quick switch supports rapid alternation

### 8.3 Transition Rules

- no hard reset of workspace unless requested
- unresolved blockers remain visible across studios

## 9. Multiple Windows

### 9.1 Use Cases

- compare assets side by side
- isolate diagnostics from production canvas
- monitor activity while authoring

### 9.2 Window Modes

- Linked mode: shared selection and context sync
- Independent mode: separate tasks within same project

### 9.3 Coordination

- users choose sync granularity (selection, filters, inspector state)
- each window can store role profile (authoring, review, monitoring)

## 10. Multiple Monitors

### 10.1 Allocation Patterns

- Monitor 1: core editing or composition
- Monitor 2: inspector, activity, diagnostics, references

### 10.2 Behavior

- reconnect logic restores prior monitor allocation when available
- graceful fallback when displays are removed

### 10.3 Attention Management

- high-severity alerts appear on active monitor and mirrored in status bar
- low-severity updates remain localized to secondary surfaces

## 11. Workspace Modes

### 11.1 Explore Mode

- broad navigation, high discoverability, expanded references

### 11.2 Build Mode

- minimized chrome, high focus, prioritized production controls

### 11.3 Resolve Mode

- diagnostics-forward, compare-capable layout, explicit decision surfaces

Mode can be manually set or context-suggested.

## 12. Session Continuity

### 12.1 Resume Experience

On reopen, Atlas restores:

- last active project/studio
- open tabs and panel states
- running or pending workflow context
- unresolved decisions and blockers

### 12.2 Recovery Paths

- restore previous layout snapshot
- open recent workspace sessions
- reset layout without losing project data

## 13. Workspace Permissions (Team Context)

Team spaces may define:

- who can publish shared layouts
- who can modify canonical templates
- who can pin mandatory panels for compliance workflows

Permissions should be visible and explainable to users.

## 14. Workspace Performance Perception

Perceived responsiveness guidelines:

- layout transitions should feel immediate and deterministic
- panel open/close operations must preserve continuity
- switching projects should show progressive context loading

## 15. Workspace Quality Criteria

The workspace system is successful when users can:

- maintain flow across complex tasks without rebuilding setup
- switch studios quickly without losing orientation
- recover from mistakes in arrangement instantly
- scale from single-screen beginner use to multi-monitor expert operation