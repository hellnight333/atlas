# Atlas Blueprint 12: Status Bar

## Purpose

Blueprint Status Bar as the ambient operational telemetry strip with strict non-overlap from Activity Center and Notifications.

## Primary Users

- All users requiring continuous state awareness
- Operators monitoring system and workflow health

## Governing References

- DESKTOP_SHELL_V1.md
- ACTIVITY_MODEL.md
- PERFORMANCE_TARGETS.md
- LONG_SESSION_UX.md
- ENTERPRISE_SHELL.md

## ASCII Layout

```text
+--------------------------------------------------------------------------------------------------+
| WORKSPACE | MODELS | GPU | CLOUD | GIT | SYNC | MEMORY | RUNNING JOBS | NOTIFICATIONS | BG ACT. |
+--------------------------------------------------------------------------------------------------+
```

## Components

Mandatory status domains:

- Workspace
- Models
- GPU
- Cloud
- Git
- Sync
- Memory
- Running Jobs
- Notifications
- Background activity indicators

## Navigation

- each domain opens a deeper detail surface on activation
- running jobs opens Activity Center filtered to active in-scope records
- notifications opens notification inbox with severity filters

## Keyboard Shortcuts

- focus status bar
- move between status domains
- open selected domain detail
- jump directly to running jobs or notifications domain

## Mouse Interactions

- click domain chips for detail drill-down
- hover for compact state preview

## AI Behaviors

- anomaly hints for unusual status combinations (for example: high jobs + stale sync)
- optional concise recommendation for immediate stabilization actions

## Empty State

No active jobs and no alerts:

- show minimal healthy-state indicators
- suppress verbose telemetry noise

## Busy State

Many active jobs/background operations:

- aggregate job counts and highest severity
- prioritize clarity over per-job detail
- route detail inspection to Activity Center

## Error State

Critical status degradation:

- explicit critical marker in affected domain
- one-step path to detailed diagnostics/remediation
- persistent visibility until acknowledged/resolved per activity policy

## Responsive Behavior

- compact abbreviations for low-priority domains in narrow widths
- preserve visibility of running jobs, notifications, and workspace context at all times
- overflow domains move to status overflow menu with keyboard parity

## Accessibility Notes

- textual state labels alongside icons
- critical state announced with non-color cues
- keyboard and assistive-tech discoverability for all domain chips

## Future Expansion

- enterprise policy and tenant badges in status domains
- plugin-provided telemetry domains under governance constraints
- adaptive domain prioritization by user mode

## Ambiguity Notes

- domain overflow ordering policy under constrained width should be locked to avoid inconsistent user expectations across platforms.