# Atlas Blueprint 07: Mission Control

## Purpose

Blueprint Mission Control as the central orchestration surface for cross-project, cross-studio, and cross-agent awareness.

Mission Control is the Atlas differentiator and must function as the system-level control plane for user intent, activity, and prioritization.

## Primary Users

- Expert multi-project operators
- Team leads and creative directors
- Solo users managing parallel efforts

## Governing References

- PRODUCT_BIBLE.md
- UX_SPECIFICATION.md
- DESKTOP_SHELL_V1.md
- ACTIVITY_MODEL.md
- COMMAND_SYSTEM.md
- MULTI_WINDOW_MODEL.md
- LONG_SESSION_UX.md

## Interaction Philosophy

Mission Control answers five continuously:

1. What am I working on?
2. What are my agents doing?
3. What projects are active?
4. What assets are generating?
5. What should I do next?

Mission Control is orchestration-first, not execution-first.

It provides macro awareness, priority control, and context routing.

## ASCII Layout A: Global Mission Board

```text
+---------------------------------------------------------------------------------------------------+
| MISSION CONTROL HEADER: Scope | Time Horizon | Priority Lens | Open Command | Return to Workspace |
+-------------------------------+---------------------------------------------+--------------------+
| ACTIVE MISSIONS               | AGENT OPERATIONS                             | PRIORITY QUEUE     |
| - project-level goals         | - running agent tasks                        | - next decisions   |
| - health status               | - blocked/failed agent jobs                  | - due/at-risk work |
+-------------------------------+---------------------------------------------+--------------------+
| ACTIVE PROJECT GRID           | ASSET GENERATION STREAM                       | RISK & BLOCKERS    |
| - project cards w/ state      | - rendering/training/research outputs        | - escalation view  |
+-------------------------------+---------------------------------------------+--------------------+
| NEXT BEST ACTION PANEL: explainable recommendations + confidence + impact path                    |
+---------------------------------------------------------------------------------------------------+
```

## ASCII Layout B: Temporal Mission Timeline

```text
Time --->

[Now] | Running Jobs | Pending Decisions | Upcoming Milestones | Recent Recoveries | Completed
       |--------------|-------------------|---------------------|-------------------|---------|
       | Project A    | Publish approval  | Campaign launch     | Agent retry done  | Batch X |
       | Project B    | Asset conflict    | Research synthesis  | Render recovered  | Batch Y |
```

## ASCII Layout C: Context Routing Map

```text
User Intent
   |
   +--> Need macro overview? ----------> Mission Control
   |
   +--> Need object retrieval? --------> Universal Search
   |
   +--> Need command execution? -------> Command Palette
   |
   +--> Need fast context jump? -------> Quick Switcher
```

## Components

- Mission Header
- Active Missions panel
- Agent Operations panel
- Active Project grid
- Asset Generation stream
- Priority Queue panel
- Risk and Blockers panel
- Next Best Action panel
- Temporal Mission Timeline

## Navigation

- open focused workspace from project/mission card
- route to Activity details from agent or asset operations
- open project/studio quick switches without leaving mission context
- transition back to prior workspace preserving context state

## Keyboard Shortcuts

- enter/exit Mission Control
- cycle mission lenses (priority, risk, timeline)
- open selected project mission in workspace
- acknowledge and route blockers

## Mouse Interactions

- click mission/project cards for drill-down
- drag priority items to reorder user-level focus queue
- hover to preview dependencies and impact

## AI Behaviors

- generate explainable "what should I do next" stack
- identify cross-project bottlenecks and dependency conflicts
- summarize agent health and recommend intervention points

## Empty State

No active projects/jobs:

- show mission setup onboarding
- suggest creating first project and mission templates
- include lightweight strategy prompt cards

## Busy State

High concurrency across projects and agents:

- grouped mission cards by urgency and ownership
- escalating blocker lane
- condensed but high-fidelity agent operations feed

## Error State

Critical system/project failures:

- persistent risk block with impact summary
- direct remediation paths to affected project/activity surfaces
- conflict-safe routing when workspace is guarded read-only

## Responsive Behavior

- multi-column mission board collapses into stacked lanes by priority
- timeline view remains available as alternate compact mode
- risk and next-action lanes remain pinned in narrow mode

## Accessibility Notes

- mission cards and risk lanes keyboard navigable
- urgency coding includes text semantics and icons
- timeline and dependency summaries available in linear textual view

## Future Expansion

- enterprise mission overlays by tenant/team
- plugin-provided mission widgets under governance
- predictive capacity and risk forecasting views

## Ambiguity Notes

- mission-level recommendation arbitration between AI and user-pinned priorities needs explicit tie-break policy if both conflict.