import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button, Panel, ProjectCard } from '../../../components'
import {
  useActivityStore,
  useClusterStore,
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

  const clusterHealth = useClusterStore((state) => state.health)
  const clusterLoad = useClusterStore((state) => state.load)
  const workers = useClusterStore((state) => state.workers)
  const waitingPlacement = useClusterStore((state) => state.waitingPlacement)
  const loadCluster = useClusterStore((state) => state.loadCluster)

  useEffect(() => {
    if (open) {
      void loadCluster()
    }
  }, [loadCluster, open])

  if (!open) {
    return null
  }

  const failedWorkers = workers.filter((w) => w.status === 'offline' || w.status === 'error')

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
        <Panel
          title="Cluster Health"
          subtitle={
            clusterHealth
              ? clusterHealth.healthy
                ? 'All workers reporting'
                : 'Cluster degraded'
              : 'Loading…'
          }
        >
          <ul className="space-y-2 text-sm text-slate-300">
            <li className="rounded bg-slate-900 px-2 py-2">
              Workers: {clusterHealth?.total_workers ?? 0} · online {clusterHealth?.online ?? 0} ·
              offline {clusterHealth?.offline ?? 0}
            </li>
            <li className="rounded bg-slate-900 px-2 py-2">
              Capacity: {clusterLoad?.used_capacity ?? 0}/{clusterLoad?.total_capacity ?? 0} ·
              leases {clusterLoad?.active_leases ?? 0}
            </li>
            {waitingPlacement.length > 0 ? (
              <li className="rounded bg-amber-500/10 px-2 py-2 text-amber-200">
                {waitingPlacement.length} execution(s) awaiting placement
              </li>
            ) : null}
            {failedWorkers.length > 0 ? (
              <li className="rounded bg-rose-500/10 px-2 py-2 text-rose-200">
                Worker failures: {failedWorkers.map((w) => w.display_name).join(', ')}
              </li>
            ) : (
              <li className="rounded bg-slate-900 px-2 py-2">No worker failures</li>
            )}
          </ul>
          <Button className="mt-2 w-full" onClick={() => navigate('/cluster')}>
            Open Cluster Studio
          </Button>
        </Panel>
        <Panel title="Worker Map" subtitle="Execution placement across machines">
          <ul className="space-y-2 text-sm text-slate-300">
            {workers.length === 0 ? (
              <li className="rounded bg-slate-900 px-2 py-2">No workers registered</li>
            ) : (
              workers.map((worker) => (
                <li key={worker.id} className="rounded bg-slate-900 px-2 py-2">
                  {worker.display_name} · {worker.status} · {worker.current_load}/
                  {worker.max_concurrency} slots
                </li>
              ))
            )}
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
