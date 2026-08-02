import { useMemo } from 'react'

import { Button, Panel } from '../../../components'
import { useAssetStore, useWorkflowStore } from '../../../stores'
import type { WorkflowDefinitionPayload, WorkflowNodePayload } from '../../../api/types'

const workflowNodes: WorkflowNodePayload[] = [
  {
    id: 'import-node',
    action: 'asset.import',
    payload: {},
    depends_on: [],
    input_asset_ids: ['a1'],
    output_labels: ['imported_asset'],
    capability_req: { capability_id: 'cap-reasoning', requirements: {} },
    max_retries: 0,
    retry_delay_seconds: 0,
    failure_strategy: 'fail_fast',
    condition_expression: null,
  },
  {
    id: 'text-node',
    action: 'text.generate',
    payload: { prompt: 'Summarize the imported asset for Atlas.' },
    depends_on: ['import-node'],
    input_asset_ids: [],
    output_labels: ['text_output'],
    capability_req: { capability_id: 'cap-reasoning', requirements: { required_vram_gb: 0 } },
    max_retries: 0,
    retry_delay_seconds: 0,
    failure_strategy: 'fail_fast',
    condition_expression: null,
  },
  {
    id: 'code-node',
    action: 'code.generate',
    payload: { prompt: 'Generate code metadata for the imported asset.', language: 'python' },
    depends_on: ['text-node'],
    input_asset_ids: [],
    output_labels: ['code_output'],
    capability_req: { capability_id: 'cap-code-generation', requirements: { required_vram_gb: 0 } },
    max_retries: 0,
    retry_delay_seconds: 0,
    failure_strategy: 'fail_fast',
    condition_expression: null,
  },
  {
    id: 'image-node',
    action: 'image.generate',
    payload: { prompt: 'Generate a placeholder visual from the imported asset.' },
    depends_on: ['code-node'],
    input_asset_ids: [],
    output_labels: ['image_output'],
    capability_req: { capability_id: 'cap-image-generation', requirements: { required_vram_gb: 24 } },
    max_retries: 0,
    retry_delay_seconds: 0,
    failure_strategy: 'fail_fast',
    condition_expression: null,
  },
  {
    id: 'save-node',
    action: 'asset.save',
    payload: {},
    depends_on: ['image-node'],
    input_asset_ids: [],
    output_labels: ['saved_asset'],
    capability_req: { capability_id: 'cap-reasoning', requirements: {} },
    max_retries: 0,
    retry_delay_seconds: 0,
    failure_strategy: 'fail_fast',
    condition_expression: null,
  },
  {
    id: 'end-node',
    action: 'workflow.end',
    payload: {},
    depends_on: ['save-node'],
    input_asset_ids: [],
    output_labels: [],
    capability_req: { capability_id: 'cap-reasoning', requirements: {} },
    max_retries: 0,
    retry_delay_seconds: 0,
    failure_strategy: 'fail_fast',
    condition_expression: null,
  },
]

export function WorkflowStudioScreen() {
  const assets = useAssetStore((state) => state.assets)
  const workflows = useWorkflowStore((state) => state.workflows)
  const currentExecution = useWorkflowStore((state) => state.currentExecution)
  const timeline = useWorkflowStore((state) => state.timeline)
  const status = useWorkflowStore((state) => state.status)
  const createWorkflow = useWorkflowStore((state) => state.createWorkflow)
  const executeWorkflow = useWorkflowStore((state) => state.executeWorkflow)

  const workflowDefinition = useMemo<WorkflowDefinitionPayload>(
    () => ({
      id: 'wf-desktop-001',
      name: 'Desktop Workflow Slice 001',
      project_id: 'project-unassigned',
      workflow_id: 'wf-desktop-001',
      nodes: workflowNodes,
    }),
    [],
  )

  const activeWorkflow = workflows.find((workflow) => workflow.id === workflowDefinition.id)

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[1.35fr_1fr]">
      <Panel title="Workflow Canvas" subtitle="Create, validate, and execute the first real workflow slice">
        <div className="grid gap-2 md:grid-cols-2">
          {workflowDefinition.nodes.map((node) => (
            <div key={node.id} className="rounded border border-slate-700 bg-slate-900 p-3 text-sm text-slate-300">
              <div className="flex items-center justify-between">
                <span className="font-medium text-slate-100">{node.id}</span>
                <span className="text-xs text-slate-500">{node.action}</span>
              </div>
              <p className="mt-2 text-xs text-slate-400">Depends on: {node.depends_on.join(', ') || 'none'}</p>
              <p className="mt-1 text-xs text-slate-400">Capability: {node.capability_req.capability_id}</p>
              <p className="mt-1 text-xs text-slate-400">Status: {currentExecution?.nodes?.[node.id]?.state ?? 'draft'}</p>
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={() => void createWorkflow(workflowDefinition)}>Create Workflow</Button>
          <Button
            variant="accent"
            onClick={() => {
              if (activeWorkflow) {
                void executeWorkflow(activeWorkflow.id)
              }
            }}
          >
            Run Workflow
          </Button>
        </div>
        <p className="mt-3 text-xs text-slate-400">Validation is enforced server-side by the existing workflow engine DAG checks.</p>
      </Panel>

      <Panel title="Node Inspector" subtitle="Node library, execution state, and output assets">
        <ul className="space-y-2 text-sm text-slate-300">
          <li className="rounded bg-slate-900 px-2 py-2">Node Library: Import Asset, Generate Text, Generate Code, Generate Image, Save Asset, End</li>
          <li className="rounded bg-slate-900 px-2 py-2">Execution Status: {currentExecution?.state ?? status}</li>
          <li className="rounded bg-slate-900 px-2 py-2">Output Assets: {assets.slice(0, 4).map((asset) => asset.title).join(', ') || 'None yet'}</li>
        </ul>
      </Panel>

      <Panel title="Execution Timeline" subtitle="Queued, running, completed, failed, and produced assets">
        <div className="space-y-2 text-sm text-slate-300">
          {timeline.map((entry) => (
            <div key={String(entry.id)} className="rounded bg-slate-900 px-2 py-2">
              {String(entry.type)} · {String(entry.state ?? entry.label ?? 'state')}
            </div>
          ))}
          {timeline.length === 0 ? <p className="text-xs text-slate-400">No execution timeline yet.</p> : null}
        </div>
      </Panel>

      <Panel title="Output Assets" subtitle="Assets generated by the current execution">
        <div className="space-y-2 text-sm text-slate-300">
          {assets.map((asset) => (
            <div key={asset.id} className="rounded bg-slate-900 px-2 py-2">
              {asset.title} · {asset.type} · v{asset.version}
            </div>
          ))}
        </div>
      </Panel>
    </section>
  )
}