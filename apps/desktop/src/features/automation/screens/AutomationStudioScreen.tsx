import { useEffect, useMemo, useState } from 'react'

import { Button, Panel } from '../../../components'
import { useAutomationStore, useProjectStore } from '../../../stores'
import type {
  AutomationAction,
  AutomationCondition,
  AutomationRule,
  AutomationTriggerType,
} from '../../../api/types'
import { ACTION_TYPES, CONDITION_OPERATORS, CONDITION_TYPES, TRIGGER_TYPES } from '../constants'
import { RuleEditor } from '../components/RuleEditor'
import { RunHistory } from '../components/RunHistory'
import { RunLogs } from '../components/RunLogs'

export function AutomationStudioScreen() {
  const projects = useProjectStore((state) => state.projects)
  const project = projects[0]

  const rules = useAutomationStore((state) => state.rules)
  const activeRule = useAutomationStore((state) => state.activeRule)
  const history = useAutomationStore((state) => state.history)
  const logs = useAutomationStore((state) => state.logs)
  const runState = useAutomationStore((state) => state.state)
  const conflicts = useAutomationStore((state) => state.conflicts)
  const lastRun = useAutomationStore((state) => state.lastRun)
  const status = useAutomationStore((state) => state.status)

  const loadRules = useAutomationStore((state) => state.loadRules)
  const loadConflicts = useAutomationStore((state) => state.loadConflicts)
  const createRule = useAutomationStore((state) => state.createRule)
  const updateRule = useAutomationStore((state) => state.updateRule)
  const deleteRule = useAutomationStore((state) => state.deleteRule)
  const toggleRule = useAutomationStore((state) => state.toggleRule)
  const runRule = useAutomationStore((state) => state.runRule)
  const dryRunRule = useAutomationStore((state) => state.dryRunRule)
  const setActiveRule = useAutomationStore((state) => state.setActiveRule)

  const [name, setName] = useState('New Automation')
  const [triggerType, setTriggerType] = useState<AutomationTriggerType>('manual')
  const [conditions, setConditions] = useState<AutomationCondition[]>([])
  const [actions, setActions] = useState<AutomationAction[]>([])
  const [priority, setPriority] = useState(0)

  useEffect(() => {
    void loadRules(project?.id)
    void loadConflicts(project?.id)
  }, [loadConflicts, loadRules, project?.id])

  const conflictingRuleIds = useMemo(
    () => new Set(conflicts.flatMap((conflict) => conflict.rule_ids)),
    [conflicts],
  )

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[300px_minmax(0,1fr)_340px]">
      <Panel title="Automation Rules" subtitle="Every execution starts with an explicit trigger">
        <div className="space-y-3">
          <Button
            variant="accent"
            className="w-full"
            onClick={() => {
              void createRule({
                name,
                description: `Triggered by ${triggerType}`,
                trigger: { type: triggerType, metadata: {} },
                conditions,
                actions,
                projectId: project?.id,
                priority,
              })
            }}
          >
            Create Rule
          </Button>

          {rules.length === 0 ? (
            <p className="rounded border border-dashed border-slate-700 px-3 py-6 text-center text-sm text-slate-500">
              {status === 'loading' ? 'Loading rules…' : 'No automation rules yet.'}
            </p>
          ) : null}

          <div className="space-y-2">
            {rules.map((rule) => (
              <RuleListItem
                key={rule.id}
                rule={rule}
                selected={activeRule?.id === rule.id}
                conflicting={conflictingRuleIds.has(rule.id)}
                onSelect={() => setActiveRule(rule)}
                onToggle={() => void toggleRule(rule.id, !rule.enabled)}
              />
            ))}
          </div>
        </div>
      </Panel>

      <Panel title="Rule Editor" subtitle="Trigger → Conditions → Planner → Scheduler → Runtime → Outputs">
        <RuleEditor
          name={name}
          triggerType={triggerType}
          conditions={conditions}
          actions={actions}
          priority={priority}
          triggerTypes={TRIGGER_TYPES}
          conditionTypes={CONDITION_TYPES}
          conditionOperators={CONDITION_OPERATORS}
          actionTypes={ACTION_TYPES}
          activeRule={activeRule}
          onNameChange={setName}
          onTriggerChange={setTriggerType}
          onConditionsChange={setConditions}
          onActionsChange={setActions}
          onPriorityChange={setPriority}
          onSave={() => {
            if (!activeRule) {
              return
            }
            void updateRule(activeRule.id, {
              name,
              trigger: { type: triggerType, metadata: {} },
              conditions,
              actions,
              priority,
            })
          }}
          onLoadIntoEditor={() => {
            if (!activeRule) {
              return
            }
            setName(activeRule.name)
            setTriggerType(activeRule.trigger.type)
            setConditions(activeRule.conditions)
            setActions(activeRule.actions)
            setPriority(activeRule.priority)
          }}
        />
      </Panel>

      <div className="space-y-4">
        <Panel title="Controls" subtitle="Manual run, dry run, enable, delete">
          <div className="grid gap-2">
            <Button
              variant="accent"
              disabled={!activeRule}
              onClick={() => activeRule && void runRule(activeRule.id)}
            >
              Manual Run
            </Button>
            <Button disabled={!activeRule} onClick={() => activeRule && void dryRunRule(activeRule.id)}>
              Dry Run
            </Button>
            <Button
              disabled={!activeRule}
              onClick={() => activeRule && void toggleRule(activeRule.id, !activeRule.enabled)}
            >
              {activeRule?.enabled ? 'Disable' : 'Enable'}
            </Button>
            <Button
              variant="ghost"
              disabled={!activeRule}
              onClick={() => activeRule && void deleteRule(activeRule.id)}
            >
              Delete
            </Button>
          </div>

          {lastRun ? (
            <div className="mt-3 rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm">
              <div className="text-xs uppercase tracking-widest text-slate-500">Last Run</div>
              <div className="mt-1 text-slate-100">
                {lastRun.status}
                {lastRun.duration_ms != null ? ` · ${lastRun.duration_ms}ms` : ''}
              </div>
              {lastRun.error ? <p className="mt-1 text-xs text-rose-300">{lastRun.error}</p> : null}
            </div>
          ) : null}

          {runState ? (
            <div className="mt-3 space-y-1 text-sm text-slate-300">
              <StateRow label="Total Runs" value={String(runState.total_runs)} />
              <StateRow label="Failures" value={String(runState.failure_count)} />
              <StateRow label="Next Run" value={runState.next_run_at ?? 'Not scheduled'} />
            </div>
          ) : null}
        </Panel>

        <Panel title="Execution History" subtitle="Start · finish · duration · status · retries">
          <RunHistory runs={history} />
        </Panel>

        <Panel title="Run Logs" subtitle="Audit trail with actor attribution">
          <RunLogs logs={logs} />
        </Panel>
      </div>
    </section>
  )
}

function RuleListItem({
  rule,
  selected,
  conflicting,
  onSelect,
  onToggle,
}: {
  rule: AutomationRule
  selected: boolean
  conflicting: boolean
  onSelect: () => void
  onToggle: () => void
}) {
  return (
    <div
      className={`rounded border px-3 py-2 ${selected ? 'border-cyan-500/50 bg-cyan-500/10' : 'border-slate-800 bg-slate-900'}`}
    >
      <button type="button" className="block w-full text-left" onClick={onSelect}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium text-slate-100">{rule.name}</span>
          <span
            className={`text-xs uppercase tracking-widest ${rule.enabled ? 'text-emerald-300' : 'text-slate-500'}`}
          >
            {rule.enabled ? 'on' : 'off'}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          {rule.trigger.type} · priority {rule.priority} · {rule.actions.length} action(s)
        </p>
        {conflicting ? (
          <p className="mt-1 text-xs text-amber-300">Conflict: same trigger and priority as another rule</p>
        ) : null}
      </button>
      <button
        type="button"
        className="mt-2 text-xs text-slate-400 underline-offset-2 hover:text-slate-200 hover:underline"
        onClick={onToggle}
      >
        {rule.enabled ? 'Disable' : 'Enable'}
      </button>
    </div>
  )
}

function StateRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-900 px-3 py-2">
      <div className="text-xs uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-1 text-slate-100">{value}</div>
    </div>
  )
}
