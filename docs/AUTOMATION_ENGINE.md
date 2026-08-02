# Atlas Automation Engine

## Objective

The Automation Engine runs deterministic workflows that begin with an explicit trigger.

Automation is not autonomy. It behaves like GitHub Actions, Zapier or Jenkins — never like a
self-directing agent. Every execution has a cause, an explanation and a reproducible record.

```
Trigger → Conditions → Planner → Scheduler → Runtime → Outputs
```

## Responsibilities

- rule storage and lifecycle (create, update, delete, enable, disable)
- deterministic trigger evaluation
- deterministic condition evaluation
- priority ordering and conflict detection
- manual run and dry run
- run history, logs and audit trail
- graph lineage for every execution

## Non-Responsibilities

- no provider calls
- no provider or model selection
- no execution engine of its own
- no autonomous goal generation
- no recursive or self-directed planning
- no hidden executions

The engine never imports `ProviderManager`, `ProviderRouter` or `ExecutionPolicyEngine`.
`packages/kernel/tests/test_automation.py` enforces this with an AST contract test.

## The one rule

**Automation only enqueues work through the existing Scheduler → Runtime → Worker pipeline.**

Automation builds `PlanStep`s, submits a `SchedulerRequest` to `AgentScheduler`, then calls
`AgentRuntime.start_schedule`. The runtime owns execution and the Execution Policy remains the
sole owner of provider selection. Automation never bypasses that path.

## Action kinds

Every action type resolves through `ACTION_CATALOG` to one of two kinds.

| Kind | Behaviour | Actions |
|---|---|---|
| `EXECUTABLE` | becomes a `PlanStep` → Scheduler → Runtime → Worker | `run_planner`, `queue_workflow`, `start_runtime`, `generate_asset`, `generate_image`, `generate_video` |
| `STATE` | mutates kernel records only, never reaches a provider | `run_review`, `send_notification`, `create_task`, `create_report`, `archive_asset`, `publish_asset`, `update_metadata` |

An unknown action type is rejected at rule creation and at update time.

## Triggers

`manual`, `timer`, `cron`, `asset_imported`, `asset_updated`, `asset_published`,
`review_approved`, `review_rejected`, `workflow_completed`, `workflow_failed`,
`agent_completed`, `project_created`, `project_opened`, `research_completed`,
`image_generated`, `video_generated`.

Event triggers require a payload. A rule fired with no event data is skipped rather than run —
this is why `run_rule` passes `trigger_data` to `evaluate_trigger` before normalising it.

`timer` and `cron` rules register a row in `atlas_automation_schedules` carrying `next_run`
and `last_run`. The existing scheduler owns timing; automation only records intent.

## Conditions

Operators: `equals`, `not_equals`, `in`, `contains`, `not_contains`, `greater_than`,
`less_than`, `between`, `exists`, `not_exists`, `graph_relationship_exists`.

All conditions must match for the rule to proceed. An empty condition list always matches.
An unsupported operator raises rather than silently passing.

## Rule ordering and conflicts

Rules are evaluated in descending `priority`, then by creation time, then by id — a total
order, so dispatch is reproducible. `detect_conflicts` reports any two enabled rules that
share a trigger *and* a priority, since their relative order is arbitrary.

Rule priority maps onto scheduler priority: `>=100` immediate, `>=50` high, `0` normal,
`<0` low, `<=-50` background.

## Run outcomes

| Status | Meaning |
|---|---|
| `completed` | all actions applied |
| `skipped` | rule disabled, trigger unsatisfied, or conditions unmet |
| `failed` | an action raised, or a runtime execution failed or timed out |

A failing rule never raises into the trigger path — `handle_event` records the failure on the
run and continues, so one broken rule cannot break an unrelated event producer.

## Persistence

Additive tables only:

- `atlas_automation_rules`
- `atlas_automation_runs`
- `atlas_automation_logs`
- `atlas_automation_schedules`

## API

| Method | Path |
|---|---|
| GET | `/automation` |
| POST | `/automation` |
| GET | `/automation/{id}` |
| PUT | `/automation/{id}` |
| DELETE | `/automation/{id}` |
| POST | `/automation/{id}/enable` |
| POST | `/automation/{id}/disable` |
| POST | `/automation/{id}/run` |
| POST | `/automation/{id}/dry-run` |
| GET | `/automation/{id}/history` |
| GET | `/automation/{id}/state` |
| GET | `/automation/runs` |
| GET | `/automation/logs` |
| GET | `/automation/conflicts` |

## Events

`AutomationRuleCreated`, `AutomationRuleUpdated`, `AutomationRuleDeleted`,
`AutomationRuleEnabled`, `AutomationRuleDisabled`, `AutomationTriggered`,
`AutomationStarted`, `AutomationCompleted`, `AutomationFailed`, `AutomationSkipped`.

## Graph lineage

Rule creation writes an `automation_rule` node. A successful run writes an `automation_run`
node plus an `executed_by` edge back to the rule, and a `generated_from` edge from every
produced asset to the run. The chain stays intact:

```
Automation Rule → Run → Schedule → Execution → Assets
```

## Audit

Every lifecycle change writes an `atlas_automation_logs` row carrying the `actor` that caused
it — created, updated, enabled, disabled, executed. Audit rows have no `run_id`; run-scoped
log rows do.

## Dry run

A dry run evaluates the trigger and conditions for real, then reports the plan steps it would
have submitted without creating a schedule or a runtime execution. State actions report
`applied: false`. `dry_run` can be set per invocation or pinned on the rule.

## Desktop

`/automation` — Automation Studio. Rule list with conflict badges, a visual pipeline editor
(trigger → conditions → actions → scheduler/runtime), execution history, run logs, and
enable/disable/manual-run/dry-run controls. The editor is visual only; there is no code editor.

## Tests

`packages/kernel/tests/test_automation.py` covers rule creation, trigger evaluation, condition
evaluation, scheduler submission, runtime execution, history, retry, timeout, disable, dry run,
event emission, graph lineage, and the architecture contracts.
