# Atlas Blueprint 03: Project Workspace

## Purpose

Blueprint the active project environment where planning, production, review, and history converge.

## Primary Users

- Project owners
- Contributors and specialists
- Reviewers and operators

## Governing References

- INFORMATION_ARCHITECTURE.md
- DESKTOP_SHELL_V1.md
- WORKSPACE_SYSTEM.md
- ACTIVITY_MODEL.md
- MULTI_WINDOW_MODEL.md
- STUDIO_TAXONOMY.md
- ENTERPRISE_SHELL.md

## ASCII Layout

```text
+--------------------------------------------------------------------------------------------------+
| PROJECT HEADER: Project Name | Owner Scope | Studio Selector | Version Marker | Open Mission Ctrl |
+--------------------------+-----------------------------------------------------+-------------------+
| PROJECT NAV PANEL        | MAIN WORKSPACE                                      | INSPECTOR         |
| - Files/Docs             | - Active view (board/editor/canvas/list/timeline)  | - Object details  |
| - Assets                 | - Split views                                       | - Metadata        |
| - Studios                | - Collaboration placeholders                         | - History/versions|
| - Timeline               | - Local project overview modules                    | - AI guidance     |
+--------------------------+-----------------------------------------------------+-------------------+
| PROJECT HISTORY + VERSION STRIP: checkpoints, changes, compare, rollback entry points            |
+--------------------------------------------------------------------------------------------------+
| STATUS BAR + ACTIVITY SIGNALS                                                                      |
+--------------------------------------------------------------------------------------------------+
```

## Components

- Project Header
- Project Navigation panel (files/assets/studios/timeline)
- Main Workspace views
- Inspector
- Project History and Version strip
- Collaboration placeholders (presence/ownership indicators)

## Navigation

- project-internal navigation via project nav panel
- studio switch preserving project scope
- history/versions quick jump and compare
- command-based jump to files/assets/timeline nodes

## Keyboard Shortcuts

- cycle project sections
- open selected file/asset/studio
- toggle split views and inspector
- open project history compare mode
- open command system and quick switcher

## Mouse Interactions

- drag files/assets into workspace views
- drag tabs for split and window detach
- click version checkpoints for compare preview

## AI Behaviors

- context-aware project risk highlights
- suggestions for next workflow stage based on project state
- anomaly notices for blocked dependencies or stale tasks

## Empty State

New project with no assets:

- starter project structure actions
- suggested studio entry points
- first milestone setup cards

## Busy State

Project under heavy execution:

- active jobs summarized in task strip
- timeline highlights in-progress and blocked items
- inspector shows object-level execution impacts where relevant

## Error State

Project-level failures:

- guarded actions for invalid dependencies
- direct links to Activity details and remediation paths
- optional temporary read-only state for conflicted objects

## Responsive Behavior

- narrow mode collapses project nav to compact drawer
- inspector becomes toggle drawer
- project history strip condenses into checkpoint menu

## Accessibility Notes

- deterministic focus order across header/nav/workspace/inspector/history
- all project actions reachable through keyboard and command system
- collaboration placeholders include textual role and ownership cues

## Future Expansion

- enterprise policy overlays in project header
- plugin-provided project panels under governance constraints
- advanced project graph view in future mission workflows

## Ambiguity Notes

- collaboration placeholders are structural only; real-time editing semantics remain governed by MULTI_WINDOW_MODEL.md and future collaboration architecture.