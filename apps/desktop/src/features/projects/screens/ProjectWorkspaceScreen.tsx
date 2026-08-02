import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { Button, Panel } from '../../../components'
import { useActivityStore, useAssetStore, useProjectStore, useWorkspaceIntelligenceStore } from '../../../stores'

export function ProjectWorkspaceScreen() {
  const navigate = useNavigate()
  const { id } = useParams()
  const project = useProjectStore((state) => state.projects.find((candidate) => candidate.id === id) ?? state.projects[0])
  const jobs = useActivityStore((state) => state.jobs)
  const projectAssetsState = useAssetStore((state) => (project ? state.projectAssets[project.id] : undefined))
  const loadProjectAssets = useAssetStore((state) => state.loadProjectAssets)
  const setSelectedAssetId = useAssetStore((state) => state.setSelectedAssetId)
  const dashboard = useWorkspaceIntelligenceStore((state) => state.dashboard)
  const loadWorkspaceIntelligence = useWorkspaceIntelligenceStore((state) => state.loadForProject)

  useEffect(() => {
    if (project?.id) {
      void loadProjectAssets(project.id)
      void loadWorkspaceIntelligence(project.id)
    }
  }, [loadProjectAssets, loadWorkspaceIntelligence, project?.id])

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[1.2fr_1fr]">
      <Panel title="Workspace + Files + Assets" subtitle={`${project?.name ?? 'Project'} · active project board with split tabs`}>
        <List items={['Files', 'Timeline', 'Studios', 'Project Overview']} />
        <div className="mt-3 space-y-2">
          <p className="text-xs uppercase tracking-widest text-slate-500">Live Project Assets</p>
          {(projectAssetsState?.data ?? []).map((asset) => (
            <button
              key={asset.id}
              type="button"
              className="block w-full rounded bg-slate-900 px-2 py-2 text-left text-sm text-slate-300 hover:bg-slate-800"
              onClick={() => {
                setSelectedAssetId(asset.id)
                navigate(`/asset/${asset.id}`)
              }}
            >
              {asset.title} · v{asset.version}
            </button>
          ))}
          {projectAssetsState?.status === 'loading' || projectAssetsState?.status === 'refreshing' ? (
            <p className="text-xs text-slate-400">Loading project assets...</p>
          ) : null}
        </div>
      </Panel>
      <Panel title="History + Versioning" subtitle="Checkpoint strip and compare entry points">
        <List items={(dashboard?.recent_timeline ?? []).slice(0, 5).map((item) => `${String(item.type)} - ${String(item.title)}`)} />
      </Panel>
      <Panel title="Collaboration Placeholder" subtitle="Presence and ownership markers">
        <p className="text-xs text-slate-400">TODO: Finalize real-time collaboration and role arbitration flow.</p>
      </Panel>
      <Panel title="Project Activity" subtitle="Project-scoped running and failed jobs">
        <List items={jobs.map((job) => `${job.name} - ${job.state}`)} />
      </Panel>
      <Panel title="Import Asset" subtitle="Real kernel-backed asset import">
        <ImportAssetForm projectId={project?.id ?? 'p1'} />
      </Panel>
      <Panel title="Project Summary" subtitle="Workspace Intelligence dashboard snapshot on open">
        <List
          items={[
            String(dashboard?.project_summary?.summary ?? 'No summary yet'),
            `Project health: running ${Number(dashboard?.project_health?.running_jobs ?? 0)}, blocked ${Number(dashboard?.project_health?.blocked_jobs ?? 0)}`,
            `Research progress: ${Number(dashboard?.research_progress?.active_sessions ?? 0)} active`,
            `Review queue: ${(dashboard?.review_queue ?? []).length}`,
            `Image queue: ${(dashboard?.image_queue ?? []).length}`,
            `Knowledge growth: ${Number(dashboard?.knowledge_growth?.research_assets ?? 0)}`,
          ]}
        />
      </Panel>
      <Panel title="Recent Workflows" subtitle="Suggested workflow continuity and recent runs">
        <List
          items={
            (dashboard?.recent_workflows ?? []).length > 0
              ? (dashboard?.recent_workflows ?? []).slice(0, 5).map((workflow) => String(workflow.name ?? workflow.id ?? 'workflow'))
              : ['No workflow history yet']
          }
        />
      </Panel>
    </section>
  )
}

function ImportAssetForm({ projectId }: { projectId: string }) {
  const importAsset = useAssetStore((state) => state.importAsset)
  const status = useAssetStore((state) => state.status)
  const error = useAssetStore((state) => state.error)

  return (
    <div className="space-y-3">
      <input
        type="file"
        className="block w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-300"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (!file) {
            return
          }
          void importAsset({ file, projectId, tags: ['desktop-import'] })
        }}
      />
      <div className="flex items-center gap-2">
        <Button type="button">Retry</Button>
        <Button type="button" variant="ghost">Cancel</Button>
      </div>
      {status === 'refreshing' ? <p className="text-xs text-slate-400">Upload in progress...</p> : null}
      {error ? <p className="text-xs text-rose-300">Import failed: {error.message}</p> : null}
    </div>
  )
}

function List({ items }: { items: string[] }) {
  return (
    <ul className="space-y-1 text-sm text-slate-300">
      {items.map((item) => (
        <li key={item} className="rounded bg-slate-900 px-2 py-1">
          {item}
        </li>
      ))}
    </ul>
  )
}
