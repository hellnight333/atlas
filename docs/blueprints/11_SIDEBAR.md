# Atlas Blueprint 11: Sidebar

## Purpose

Blueprint Sidebar as the structural navigation spine for Atlas with scalable studio and project discovery.

## Primary Users

- All users navigating core surfaces
- Power users using pinned/favorite pathways
- Enterprise users operating under role/policy visibility constraints

## Governing References

- DESKTOP_SHELL_V1.md
- STUDIO_TAXONOMY.md
- INFORMATION_ARCHITECTURE.md
- ENTERPRISE_SHELL.md
- COMMAND_SYSTEM.md

## ASCII Layout

```text
+---------------------------------------------+
| SIDEBAR HEADER: Workspace Switcher          |
+---------------------------------------------+
| CORE                                         |
| - Home                                       |
| - Projects                                   |
| - Activity                                   |
+---------------------------------------------+
| STUDIOS (taxonomy-governed)                  |
| - Capability groups                          |
| - Favorite Studios                           |
| - Recent Studios                             |
| - Pinned Studios                             |
+---------------------------------------------+
| WORK SURFACES                                |
| - Assets                                     |
| - Research                                   |
| - Marketplace                                |
| - Settings                                   |
+---------------------------------------------+
| ENTERPRISE                                   |
| - Org/Tenant context                         |
| - Role and policy indicators                 |
+---------------------------------------------+
```

## Components

- Sidebar Header with Workspace Switcher
- Core destinations group
- Studios group (capability + favorite/recent/pinned)
- Work surfaces group
- Enterprise context group

## Navigation

- open destinations with context-preserving transitions
- switch workspace and studio without losing project scope
- route to quick switcher and mission control entry points from header region

## Keyboard Shortcuts

- focus sidebar and move between groups
- open selected destination
- pin/unpin selected studio or project shortcut
- collapse/expand sidebar modes

## Mouse Interactions

- click destinations
- drag reorder for user-managed pins/favorites
- expand/collapse groups and capability sections

## AI Behaviors

- suggest temporary shortcut pins for active session patterns
- recommend studio jumps when workflow context indicates mismatch
- propose cleanup of stale pins/recent clutter

## Empty State

No pins/favorites/recent data:

- show setup prompts for favorites and starter studios
- provide capability-first browse links

## Busy State

High context-switch activity:

- highlight currently active and recently switched scopes
- keep group summaries compact with quick expansion

## Error State

Policy-restricted or unavailable destination:

- disabled entry with reason indicator
- link to available alternative path where applicable

## Responsive Behavior

- expanded, compact, icon-only modes
- in narrow widths, secondary groups collapse first
- core and active context remain visible in all modes

## Accessibility Notes

- group landmarks and destination labels clearly exposed
- keyboard traversal deterministic across grouped sections
- policy and role indicators include textual explanations

## Future Expansion

- plugin/marketplace studio insertions via governed taxonomy slots
- enterprise-managed destination bundles
- adaptive sidebar presets by workspace mode

## Ambiguity Notes

- if enterprise policy hides a studio that is user-pinned, precedence and fallback display behavior require explicit policy hierarchy definition.