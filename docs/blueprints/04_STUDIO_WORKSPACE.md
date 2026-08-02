# Atlas Blueprint 04: Studio Workspace

## Purpose

Blueprint a single Studio operating environment inside a project context.

## Primary Users

- Domain specialists using studio-specific tools
- Cross-functional contributors switching task lenses

## Governing References

- STUDIO_TAXONOMY.md
- DESKTOP_SHELL_V1.md
- COMPONENT_LIBRARY.md
- ACTIVITY_MODEL.md
- COMMAND_SYSTEM.md
- UNIVERSAL_SEARCH.md

## ASCII Layout

```text
+------------------------------------------------------------------------------------------------+
| STUDIO HEADER: Capability > Studio | Workspace Template | Scope Filters | Open Command/Search |
+-------------------------------+-------------------------------------------+---------------------+
| STUDIO TOOLBAR                | CANVAS / PRIMARY VIEW                     | INSPECTOR          |
| - Studio actions              | - Production surface                       | - Parameters       |
| - Quick mode toggles          | - Split preview/edit modes                 | - Metadata         |
| - Workflow stage controls     | - Embedded context breadcrumbs             | - AI suggestions   |
+-------------------------------+-------------------------------------------+---------------------+
| ASSET RAIL                    | HISTORY + PREVIEW STRIP                   | BACKGROUND TASKS   |
| - Inputs/outputs              | - Versions/checkpoints                     | - Active operations|
+------------------------------------------------------------------------------------------------+
| STATUS BAR                                                                                     |
+------------------------------------------------------------------------------------------------+
```

## Components

- Studio Header
- Studio Toolbar
- Canvas / Primary View
- Parameters and Inspector
- Preview and History strip
- Asset Rail
- Background Task dock

## Navigation

- switch studio within project scope
- switch workspace templates for same studio
- open related assets and workflow steps from canvas context
- jump to search/commands with studio-scoped defaults

## Keyboard Shortcuts

- focus studio toolbar/canvas/inspector/asset rail
- stage navigation within active workflow
- open quick action list for selected object
- open command/search with studio scope preselected

## Mouse Interactions

- drag assets into canvas
- adjust parameters via inspector controls
- drag split handles for edit/preview density

## AI Behaviors

- studio-specific recommendations for next actions
- parameter sanity hints and quality alerts
- suggest recoveries for blocked studio tasks

## Empty State

Studio opened with no relevant inputs:

- suggest required starter assets
- show "begin workflow" pathway
- offer template-based quick start cards

## Busy State

Multiple studio operations active:

- Background Tasks dock shows running and blocked
- canvas overlays indicate pending outputs where relevant

## Error State

Studio operation failures:

- localized error cards tied to affected tool/action
- inspector shows failure context and remediation
- escalation to activity/notifications by activity policy

## Responsive Behavior

- inspector collapses to drawer on narrow widths
- asset rail compacts to icon mode
- preview/history strip can collapse into tabbed bottom drawer

## Accessibility Notes

- keyboard path for every major studio action
- parameter changes confirmed with non-color feedback
- AI suggestions screen-reader discoverable and dismissible

## Future Expansion

- plugin and marketplace tools inside studio under governance
- enterprise-managed studio variants
- advanced compare and simulation panels for expert modes

## Ambiguity Notes

- when a tool can belong to multiple studios, primary studio ownership must follow STUDIO_TAXONOMY.md capability mapping.