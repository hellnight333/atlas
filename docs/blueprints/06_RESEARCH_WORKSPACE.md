# Atlas Blueprint 06: Research Workspace

## Purpose

Blueprint Research mode as a structured synthesis environment for sources, notes, memory, and knowledge linking.

## Primary Users

- Researchers and strategists
- Writers and analysts
- Product and creative teams collecting evidence

## Governing References

- INFORMATION_ARCHITECTURE.md
- UX_SPECIFICATION.md
- DESKTOP_SHELL_V1.md
- UNIVERSAL_SEARCH.md
- ACTIVITY_MODEL.md

## ASCII Layout

```text
+---------------------------------------------------------------------------------------------------+
| RESEARCH HEADER: Collection Scope | Query Context | Source Filters | Open Search | Open Command   |
+-------------------------------------+-------------------------------------------+----------------+
| SOURCES PANEL                        | KNOWLEDGE GRAPH / NOTES CANVAS            | INSPECTOR      |
| - source list                        | - linked concepts                          | - citation     |
| - trust/freshness markers            | - notes and synthesis nodes                | - metadata     |
| - import and capture actions         | - relationship edges                       | - AI summary   |
+-------------------------------------+-------------------------------------------+----------------+
| MEMORY PANEL                         | COLLECTIONS + REFERENCES                   | ACTIVITY HINTS |
| - reusable knowledge                 | - grouped evidence sets                    | - long jobs    |
+---------------------------------------------------------------------------------------------------+
| STATUS BAR                                                                                         |
+---------------------------------------------------------------------------------------------------+
```

## Components

- Research Header
- Sources panel
- Knowledge Graph / Notes canvas
- Memory panel
- Collections and References panel
- Inspector
- Activity hints

## Navigation

- navigate from source to note to graph node to memory artifact
- switch collections while preserving query context
- jump to related assets/workflows from references

## Keyboard Shortcuts

- focus sources/graph/notes/memory/inspector regions
- create note node and link to selected source
- open universal search pre-scoped to research context

## Mouse Interactions

- drag source into note canvas to create citation-linked nodes
- connect graph nodes to express relationship hypotheses
- expand/collapse source clusters

## AI Behaviors

- summarize source clusters and key claims
- suggest missing citations for unsupported notes
- surface contradiction and confidence cues in synthesis graph

## Empty State

No sources or notes:

- guided capture options (import, search, paste source)
- starter synthesis template
- default collection creation prompt

## Busy State

Research ingestion or analysis running:

- progress and state in activity hints
- source trust/freshness update signals

## Error State

Source fetch or analysis failure:

- source card-level error indicators
- fallback to last known indexed context where allowed
- route to activity details for remediation

## Responsive Behavior

- graph canvas remains primary; side panels collapse to drawers
- memory/collections become tabbed bottom panel in narrow widths

## Accessibility Notes

- citation links keyboard reachable from notes and graph nodes
- textual alternatives for graph relationship indicators
- clear focus and announce behavior for dynamic source updates

## Future Expansion

- enterprise-approved source connectors
- plugin analyzers for specialized domains
- mission-level research heatmap summary

## Ambiguity Notes

- confidence scoring semantics for AI summaries require alignment with future research quality framework to avoid interpretation drift.