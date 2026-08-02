# Atlas Blueprint 02: Home Workspace

## Purpose

Define the Home workspace blueprint as the session entry and re-entry surface for momentum restoration.

## Primary Users

- Returning solo users
- Team contributors resuming active work
- New users after initial setup

## Governing References

- UX_SPECIFICATION.md
- INFORMATION_ARCHITECTURE.md
- DESKTOP_SHELL_V1.md
- ACTIVITY_MODEL.md
- LONG_SESSION_UX.md
- COMMAND_SYSTEM.md

## ASCII Layout

```text
+-----------------------------------------------------------------------------------+
| HOME HEADER: Active Space | Active Project Scope | Session Summary | Open Command |
+------------------------------+------------------------------------+---------------+
| CONTINUE WORKING             | PINNED PROJECTS                    | AI SUGGESTIONS|
| - Last active workspaces     | - User-curated anchors             | - Next best   |
| - Resume interruptions        | - Priority indicators              | - Recovery    |
+------------------------------+------------------------------------+---------------+
| RECENT PROJECTS              | RECENT ASSETS                      | RECENT SESSIONS|
| - Recency + relevance         | - Last touched artifacts           | - Session trail|
+------------------------------+------------------------------------+----------------+
| ACTIVITY SUMMARY: running, blocked, warnings, critical, last completion outcomes  |
+-----------------------------------------------------------------------------------+
```

## Components

- Continue Working panel
- Recent Projects panel
- Pinned Projects panel
- AI Suggestions panel
- Recent Assets panel
- Recent Sessions panel
- Activity Summary strip

## Navigation

- open a project/workspace from Continue Working
- jump into pinned contexts
- open recent assets directly in project scope
- open full activity timeline from summary strip

## Keyboard Shortcuts

- move panel focus left/right and within panel lists
- quick-open highlighted project/session/asset
- open command system from any Home focus point
- invoke quick switcher without leaving Home

## Mouse Interactions

- click cards for open-in-place/open-in-new-window
- hover to preview key metadata
- context menu for pin/unpin/favorite and manage list operations

## AI Behaviors

- suggest "what should I do next" based on interrupted states and deadlines
- summarize unresolved blockers and pending decisions
- propose safe resume path after long inactivity

## Empty State

No projects exist:

- prominent create/open project actions
- starter workflow templates by user type
- short orientation checklist

## Busy State

Multiple active operations:

- activity summary shows grouped running and blocked classes
- continue section prioritizes contexts with active background operations

## Error State

Recent critical failures:

- failure summary card with direct "Open Activity Details"
- resume paths marked as guarded if dependencies unresolved

## Responsive Behavior

- three-column layout collapses to two then one with priority order:
  - Continue Working
  - Activity Summary
  - Pinned/Recent panels
- panel cards become compact summaries before hiding sections

## Accessibility Notes

- clear heading and landmark structure per panel
- keyboard-only full operation across all cards and actions
- status and priority include text and icon cues

## Future Expansion

- enterprise announcements block in policy-governed spaces
- team-presence summary for collaborative spaces
- optional mission snapshot embed from Mission Control

## Ambiguity Notes

- exact recommendation ranking between AI Suggestions and Continue Working requires product-level prioritization policy if both target the same context.