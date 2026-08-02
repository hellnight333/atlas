# Atlas Blueprint 10: Inspector

## Purpose

Blueprint Inspector as the precision context surface for selected objects, with properties, relationships, lineage, and diagnostics.

## Primary Users

- Editors making precise changes
- Reviewers validating object integrity
- Operators diagnosing and resolving issues

## Governing References

- DESKTOP_SHELL_V1.md
- COMPONENT_LIBRARY.md
- ACTIVITY_MODEL.md
- UNIVERSAL_SEARCH.md
- MULTI_WINDOW_MODEL.md

## ASCII Layout

```text
+----------------------------------------------------------------------------------+
| INSPECTOR HEADER: Selected Object | Mode (Follow/Lock/Compare) | Scope Context |
+-----------------------------------------+----------------------------------------+
| PROPERTY GROUPS                          | METADATA                               |
| - editable grouped fields                | - origin/owner/dependencies            |
+-----------------------------------------+----------------------------------------+
| RELATIONSHIPS                            | VERSIONS + TAGS                        |
| - upstream/downstream links              | - checkpoints/classification           |
+-----------------------------------------+----------------------------------------+
| AI SUGGESTIONS                           | DIAGNOSTICS + PUBLISHING               |
| - recommendations/confidence             | - warnings/readiness/issues            |
+----------------------------------------------------------------------------------+
```

## Components

- Inspector Header
- Property Groups section
- Metadata section
- Relationships section
- Versions and Tags section
- AI Suggestions section
- Diagnostics and Publishing section

## Navigation

- jump from property to related object
- open version compare from version entries
- jump from diagnostics to Activity details

## Keyboard Shortcuts

- cycle inspector sections
- expand/collapse property groups
- accept/dismiss AI suggestion action cards
- toggle follow/lock/compare modes

## Mouse Interactions

- inline editing in property fields
- drag reordering where applicable for grouped properties
- click relationship links and version checkpoints

## AI Behaviors

- context-aware quality suggestions
- highlight suspicious metadata gaps
- suggest related references and remediation pathways

## Empty State

No selected object:

- show selection guidance
- provide quick links to recent objects

## Busy State

Object under active background processing:

- read/write behavior reflects object authority state
- show progress-linked diagnostics and temporary restrictions where needed

## Error State

Object conflict or invalid state:

- visible warning in header with authority/source details
- guarded read-only sections where conflict blocks write action
- one-step route to resolution flow

## Responsive Behavior

- section stack compacts in narrow width
- less critical sections collapse by default
- compare mode offers compact diff summary when space constrained

## Accessibility Notes

- property groups and diagnostics fully keyboard accessible
- explicit labels for editable vs read-only properties
- relationship and version information available in linear text order

## Future Expansion

- plugin-defined inspector modules under governance
- enterprise policy annotations in metadata and publishing sections
- advanced relationship graph mini-view

## Ambiguity Notes

- precedence policy for conflicting AI suggestions from multiple providers requires alignment with future AI arbitration framework.