import { useNavigate } from 'react-router-dom'

import { Button, Panel, ProjectCard } from '../../../components'
import {
  useActivityStore,
  useMissionControlStore,
  useProjectStore,
  useWorkspaceIntelligenceStore,
  useWorkflowStore,
} from '../../../stores'

export function MissionControlOverlay() {
  const navigate = useNavigate()
  const open = useMissionControlStore((state) => state.open)
  const setOpen = useMissionControlStore((state) => state.setOpen)
  const projects = useProjectStore((state) => state.projects)
  const agentTasks = useActivityStore((state) => state.agentTasks)
  const currentExecution = useWorkflowStore((state) => state.currentExecution)
  const graph = useWorkspaceIntelligenceStore((state) => state.graph)

  if (!open) {
    return null
  }

  return (
    <section className="fixed inset-0 z-50 bg-slate-950/95 p-6 text-slate-100">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold">Mission Control</h2>
          <p className="text-sm text-slate-400">What you are working on, what agents are doing, and what to do next.</p>
        </div>
        <Button onClick={() => setOpen(false)}>Exit</Button>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Active Projects" subtitle="Current mission load by status">
          <div className="grid gap-2">
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
        </Panel>
        <Panel title="Running Agents" subtitle="Live agent operations">
          <ul className="space-y-2 text-sm text-slate-300">
            {agentTasks.map((task) => (
              <li key={task.id} className="rounded bg-slate-900 px-2 py-2">
                {task.name} · {task.status} · conf {(task.confidence * 100).toFixed(0)}%
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title="Suggested Next Actions" subtitle="Explainable recommendations">
          <ul className="space-y-2 text-sm text-slate-300">
            <li className="rounded bg-slate-900 px-2 py-2">Resolve blocked research dependency in Atlas SaaS Narrative</li>
            <li className="rounded bg-slate-900 px-2 py-2">Approve latest rendering outputs for Aurora Launch Film</li>
            <li className="rounded bg-slate-900 px-2 py-2">Open Activity Center failures lane and run recoverable retries</li>
          </ul>
        </Panel>
        <Panel title="Running Workflows" subtitle="Live workflow execution visibility">
          <ul className="space-y-2 text-sm text-slate-300">
            <li className="rounded bg-slate-900 px-2 py-2">
              {currentExecution ? `${currentExecution.workflow_definition_id} · ${currentExecution.state}` : 'No active workflow execution'}
            </li>
          </ul>
        </Panel>
        <Panel title="Knowledge Map" subtitle="Relationship overlay across assets, agents, executions, and workflows">
          <ul className="space-y-2 text-sm text-slate-300">
            <li className="rounded bg-slate-900 px-2 py-2">Nodes: {graph?.graph.nodes.length ?? 0}</li>
            <li className="rounded bg-slate-900 px-2 py-2">Edges: {graph?.graph.edges.length ?? 0}</li>
            <li className="rounded bg-slate-900 px-2 py-2">Execution Graph available from runtime-linked nodes.</li>
            <li className="rounded bg-slate-900 px-2 py-2">Agent Graph available from agent and team nodes.</li>
            <li className="rounded bg-slate-900 px-2 py-2">Asset Graph available from lineage and reference edges.</li>
          </ul>
        </Panel>
        <Panel title="Current Workspace" subtitle="Fast context routing">
          <div className="grid gap-2">
            <Button onClick={() => navigate('/workspace')}>Jump to Home Workspace</Button>
            <Button onClick={() => navigate('/project/p1')}>Jump to Project Workspace</Button>
            <Button onClick={() => navigate('/studio/s1')}>Jump to Studio Workspace</Button>
            <Button onClick={() => navigate('/workflow-studio')}>Jump to Workflow Studio</Button>
          </div>
        </Panel>
      </div>
    </section>
  )
}
