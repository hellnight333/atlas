# Atlas Blueprint 05: Asset Workspace

## Purpose

Blueprint asset-centric editing and analysis workspace with lineage, relationships, and publish readiness.

## Primary Users

- Creators editing media/text assets
- Reviewers validating quality and provenance
- Operators preparing assets for publishing

## Governing References

- INFORMATION_ARCHITECTURE.md
- DESKTOP_SHELL_V1.md
- ACTIVITY_MODEL.md
- UNIVERSAL_SEARCH.md
- COMMAND_SYSTEM.md

## ASCII Layout

```text
+------------------------------------------------------------------------------------------------+
| ASSET HEADER: Asset Name | Type | Project Scope | Version | Related Workflow | Open Command    |
+-----------------------------------+-------------------------------------------+----------------+
| ASSET VIEWER / EDITOR             | RELATIONSHIPS + REFERENCES PANEL          | INSPECTOR      |
| - Primary asset surface           | - Upstream inputs                          | - Metadata     |
| - Compare mode                    | - Downstream outputs                       | - Tags         |
| - Preview modes                   | - Linked artifacts and citations           | - AI analysis  |
+-----------------------------------+-------------------------------------------+----------------+
| VERSION HISTORY STRIP             | PUBLISHING PREP PANEL                      | ACTIVITY HINTS |
| - checkpoints/branches            | - target channels/checks                   | - task status  |
+------------------------------------------------------------------------------------------------+
| STATUS BAR                                                                                      |
+------------------------------------------------------------------------------------------------+
```

## Components

- Asset Header
- Viewer/Editor surface
- Relationships and References panel
- Inspector
- Version History strip
- Publishing Prep panel
- Activity hints region

## Navigation

- switch between asset versions and compare views
- navigate to related assets or originating workflows
- open publishing readiness and channel-specific requirements

## Keyboard Shortcuts

- focus viewer/inspector/relationships/history regions
- next/previous version checkpoint
- open linked reference
- open command/search with asset scope

## Mouse Interactions

- scrub timeline/checkpoint history
- drag references to relation groups
- click relationship graph nodes for dependency traversal

## AI Behaviors

- summarize quality, anomalies, and missing metadata
- suggest reference gaps and dependency risks
- propose publishing readiness improvements

## Empty State

Asset opened without structured metadata/relations:

- prompt to define metadata baseline
- suggest likely relationship candidates
- show import/add references actions

## Busy State

Asset processing active:

- in-view progress indicators for analysis/render/transform operations
- task strip and activity center linkage for detailed monitoring

## Error State

Asset operation failed:

- mark failed operation and affected version
- expose remediation path and retry in context
- preserve last stable version as default viewer target

## Responsive Behavior

- relationships panel collapses to secondary drawer on narrow widths
- version strip compacts to checkpoint dropdown
- inspector toggles between fixed and overlay modes

## Accessibility Notes

- labeled version and relationship controls
- keyboard route to every high-impact asset action
- non-color status cues for quality and errors

## Future Expansion

- plugin-provided asset analyzers under governance
- enterprise classification overlays and policy checks
- richer asset graph projections from mission-level overview

## Ambiguity Notes

- publish action semantics remain channel-policy dependent; shell only provides readiness and routing structure.