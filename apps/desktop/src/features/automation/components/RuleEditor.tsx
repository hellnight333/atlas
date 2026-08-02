import { Button } from '../../../components'
import type {
  AutomationAction,
  AutomationCondition,
  AutomationRule,
  AutomationTriggerType,
} from '../../../api/types'
import { EXECUTABLE_ACTION_TYPES } from '../constants'

type RuleEditorProps = {
  name: string
  triggerType: AutomationTriggerType
  conditions: AutomationCondition[]
  actions: AutomationAction[]
  priority: number
  triggerTypes: AutomationTriggerType[]
  conditionTypes: string[]
  conditionOperators: string[]
  actionTypes: string[]
  activeRule: AutomationRule | null
  onNameChange: (value: string) => void
  onTriggerChange: (value: AutomationTriggerType) => void
  onConditionsChange: (value: AutomationCondition[]) => void
  onActionsChange: (value: AutomationAction[]) => void
  onPriorityChange: (value: number) => void
  onSave: () => void
  onLoadIntoEditor: () => void
}

export function RuleEditor({
  name,
  triggerType,
  conditions,
  actions,
  priority,
  triggerTypes,
  conditionTypes,
  conditionOperators,
  actionTypes,
  activeRule,
  onNameChange,
  onTriggerChange,
  onConditionsChange,
  onActionsChange,
  onPriorityChange,
  onSave,
  onLoadIntoEditor,
}: RuleEditorProps) {
  const hasExecutable = actions.some((action) => EXECUTABLE_ACTION_TYPES.has(action.type))

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_120px]">
        <Field label="Rule Name">
          <input
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={name}
            onChange={(event) => onNameChange(event.target.value)}
          />
        </Field>
        <Field label="Priority">
          <input
            type="number"
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={priority}
            onChange={(event) => onPriorityChange(Number(event.target.value))}
          />
        </Field>
      </div>

      <PipelineStage step="1" title="Trigger" caption="Automation never starts on its own">
        <select
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          value={triggerType}
          onChange={(event) => onTriggerChange(event.target.value as AutomationTriggerType)}
        >
          {triggerTypes.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </PipelineStage>

      <PipelineStage step="2" title="Conditions" caption="All conditions must match">
        <div className="space-y-2">
          {conditions.map((condition, index) => (
            <div key={index} className="grid gap-2 md:grid-cols-[1fr_1fr_1fr_auto]">
              <select
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                value={condition.type}
                onChange={(event) =>
                  onConditionsChange(
                    conditions.map((item, i) => (i === index ? { ...item, type: event.target.value } : item)),
                  )
                }
              >
                {conditionTypes.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
              <select
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                value={condition.operator}
                onChange={(event) =>
                  onConditionsChange(
                    conditions.map((item, i) =>
                      i === index ? { ...item, operator: event.target.value } : item,
                    ),
                  )
                }
              >
                {conditionOperators.map((operator) => (
                  <option key={operator} value={operator}>
                    {operator}
                  </option>
                ))}
              </select>
              <input
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                placeholder="value"
                value={String(condition.value ?? '')}
                onChange={(event) =>
                  onConditionsChange(
                    conditions.map((item, i) => (i === index ? { ...item, value: event.target.value } : item)),
                  )
                }
              />
              <Button
                variant="ghost"
                onClick={() => onConditionsChange(conditions.filter((_, i) => i !== index))}
              >
                Remove
              </Button>
            </div>
          ))}
          <Button
            onClick={() =>
              onConditionsChange([
                ...conditions,
                { type: conditionTypes[0], operator: 'equals', value: '', metadata: {} },
              ])
            }
          >
            Add Condition
          </Button>
        </div>
      </PipelineStage>

      <PipelineStage
        step="3"
        title="Actions"
        caption={
          hasExecutable
            ? 'Executable actions are submitted to the Scheduler, then Runtime'
            : 'State actions update kernel records only — no provider is ever called'
        }
      >
        <div className="space-y-2">
          {actions.map((action, index) => (
            <div key={index} className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
              <select
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                value={action.type}
                onChange={(event) =>
                  onActionsChange(
                    actions.map((item, i) => (i === index ? { ...item, type: event.target.value } : item)),
                  )
                }
              >
                {actionTypes.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
              <input
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                placeholder='payload JSON e.g. {"prompt":"a blue ant"}'
                value={JSON.stringify(action.payload)}
                onChange={(event) => {
                  let parsed: Record<string, unknown> = {}
                  try {
                    parsed = JSON.parse(event.target.value) as Record<string, unknown>
                  } catch {
                    parsed = action.payload
                  }
                  onActionsChange(
                    actions.map((item, i) => (i === index ? { ...item, payload: parsed } : item)),
                  )
                }}
              />
              <Button variant="ghost" onClick={() => onActionsChange(actions.filter((_, i) => i !== index))}>
                Remove
              </Button>
            </div>
          ))}
          <Button
            onClick={() =>
              onActionsChange([...actions, { type: actionTypes[0], payload: {}, metadata: {} }])
            }
          >
            Add Action
          </Button>
        </div>
      </PipelineStage>

      <PipelineStage step="4" title="Scheduler → Runtime" caption="Owned by the kernel — not configurable here">
        <p className="rounded border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-400">
          {hasExecutable
            ? 'This rule enqueues work through the existing Scheduler, Runtime and Worker pipeline. Provider selection stays with the Execution Policy.'
            : 'This rule performs no executable work, so nothing is enqueued.'}
        </p>
      </PipelineStage>

      <div className="flex flex-wrap gap-2">
        <Button variant="accent" disabled={!activeRule} onClick={onSave}>
          Save To Selected Rule
        </Button>
        <Button disabled={!activeRule} onClick={onLoadIntoEditor}>
          Load Selected Rule
        </Button>
      </div>
    </div>
  )
}

function PipelineStage({
  step,
  title,
  caption,
  children,
}: {
  step: string
  title: string
  caption: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded border border-slate-800 bg-slate-950 p-3">
      <div className="flex items-baseline gap-2">
        <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">{step}</span>
        <h4 className="text-sm font-medium text-slate-100">{title}</h4>
      </div>
      <p className="mt-1 text-xs text-slate-500">{caption}</p>
      <div className="mt-3">{children}</div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs uppercase tracking-widest text-slate-500">{label}</span>
      {children}
    </label>
  )
}
