# Atlas Blueprint 09: Activity Center

## Purpose

Blueprint Activity Center as the canonical operational timeline projection for all execution lifecycle records.

## Primary Users

- Operators managing background work
- Contributors triaging failures/warnings
- Leads auditing progress and recovery

## Governing References

- ACTIVITY_MODEL.md
- DESKTOP_SHELL_V1.md
- LONG_SESSION_UX.md
- ENTERPRISE_SHELL.md

## ASCII Layout

```text
+--------------------------------------------------------------------------------------------------+
| ACTIVITY HEADER: Scope Filter | Severity Filter | Domain Filter | Time Filter | Search Activity |
+----------------------------------+---------------------------------------------+----------------+
| RUNNING / BLOCKED LANE            | WARNINGS / FAILURES LANE                    | SUMMARY METRICS |
| - active jobs                     | - actionable incidents                       | - counts/trends |
| - progress and elapsed            | - remediation status                         | - SLA breaches  |
+----------------------------------+---------------------------------------------+----------------+
| COMPLETED HISTORY TIMELINE                                                                  |
| [time] [domain] [state] [impact] [source] [open details] [retry/resolve where allowed]    |
+--------------------------------------------------------------------------------------------------+
| AGENT ACTIVITY | RENDERING | TRAINING | RESEARCH | PUBLISHING | DOWNLOADS | UPLOADS (group tabs) |
+--------------------------------------------------------------------------------------------------+
```

## Components

- Activity Header with filters
- Running/Blocked lane
- Warnings/Failures lane
- Completed History timeline
- Domain group tabs (rendering, research, training, publishing, downloads, uploads, agent activity)
- Summary metrics block

## Navigation

- filter timeline by scope/severity/domain/time
- jump from record to source object/project/studio
- open remediation/retry actions in relevant context

## Keyboard Shortcuts

- move focus across filter bar/lane/timeline
- expand selected record details
- apply quick severity and domain filters
- open related object from selected record

## Mouse Interactions

- click filter chips and grouped tabs
- expand records inline
- open action menus for retry/cancel/open details

## AI Behaviors

- summarize root-cause clusters by domain
- highlight likely-impacting failures first
- suggest triage sequence for large incident queues

## Empty State

No records in selected filter:

- clear explanation of active filters
- reset filter action
- optional quick links to recent scopes

## Busy State

High concurrency:

- grouped lanes remain concise
- timeline batches low-priority updates
- critical and blocked records remain pinned

## Error State

Activity Center projection unavailable or stale:

- explicit stale-state indicator
- fallback to last synchronized snapshot
- recovery action to refresh and reopen details

## Responsive Behavior

- lanes stack vertically in narrow widths
- summary metrics collapse into compact status strip
- domain tabs become horizontally scrollable selector

## Accessibility Notes

- timeline entries have structured labels for state/severity
- keyboard filter toggles for all lane pivots
- non-color incident coding with textual severity

## Future Expansion

- enterprise audit overlays and policy impact columns
- plugin-specific activity domains under trust labels
- mission-level activity synthesis feeds

## Ambiguity Notes

- retention duration and archival policy for timeline history require organization-level governance definition in enterprise operations policy.