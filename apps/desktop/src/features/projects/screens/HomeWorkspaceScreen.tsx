import { useEffect } from 'react'

import { Panel } from '../../../components'
import { useAssetStore, useProjectStore, useWorkspaceIntelligenceStore } from '../../../stores'

export function HomeWorkspaceScreen() {
  const projects = useProjectStore((state) => state.projects)
  const assets = useAssetStore((state) => state.assets)
  const activeProjectId = projects[0]?.id ?? 'p1'
  const intelligence = useWorkspaceIntelligenceStore((state) => state.context)
  const dashboard = useWorkspaceIntelligenceStore((state) => state.dashboard)
  const recent = useWorkspaceIntelligenceStore((state) => state.recent)
  const recommendations = useWorkspaceIntelligenceStore((state) => state.recommendations)
  const status = useWorkspaceIntelligenceStore((state) => state.status)
  const loadForProject = useWorkspaceIntelligenceStore((state) => state.loadForProject)

  useEffect(() => {
    void loadForProject(activeProjectId)
  }, [activeProjectId, loadForProject])

  const workspaceContext = intelligence?.workspace_context

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-3">
      <Panel title="Today's Progress" subtitle="Workspace Intelligence Engine summary for the active project">
        <List
          items={[
            `Status: ${status}`,
            `Assets touched: ${workspaceContext?.recent_assets?.length ?? 0}`,
            `Recent activity: ${workspaceContext?.recent_activity?.length ?? 0}`,
            `Open tasks: ${workspaceContext?.open_tasks?.length ?? 0}`,
            `Open reviews: ${Number(workspaceContext?.project_summary?.open_reviews ?? 0)}`,
          ]}
        />
      </Panel>

      <Panel title="Continue Working" subtitle="Recommended continuity actions and next step">
        <List
          items={[
            ...(recommendations?.recommendations?.slice(0, 4).map((item) => `${item.title}: ${item.reason}`) ?? []),
            `Suggested next step: ${recommendations?.recommendations?.[0]?.title ?? 'No recommendation yet'}`,
          ]}
        />
      </Panel>

      <Panel title="Recent AI Activity" subtitle="Conversation, research, image, and workflow intelligence">
        <List
          items={[
            `Conversations: ${workspaceContext?.recent_conversations?.length ?? 0}`,
            `Research sessions: ${workspaceContext?.recent_research?.length ?? 0}`,
            `Recent images: ${workspaceContext?.recent_images?.length ?? 0}`,
            `Workflows: ${recent?.recent_workflows?.length ?? 0}`,
          ]}
        />
      </Panel>

      <Panel title="Recent Assets" subtitle="Recently modified and pinned artifacts">
        <List
          items={[
            ...((workspaceContext?.recent_assets ?? []).slice(0, 5).map((asset) => String(asset.id ?? 'asset'))),
            `Pinned: ${(workspaceContext?.pinned_assets ?? []).length}`,
          ]}
        />
      </Panel>

      <Panel title="Open Reviews" subtitle="Review queue and running jobs from intelligence dashboard">
        <List
          items={[
            `Review queue: ${dashboard?.review_queue?.length ?? 0}`,
            `Running jobs: ${Number(dashboard?.project_health?.running_jobs ?? 0)}`,
            `Blocked jobs: ${Number(dashboard?.project_health?.blocked_jobs ?? 0)}`,
            `Image queue: ${(dashboard?.image_queue ?? []).length}`,
          ]}
        />
      </Panel>

      <Panel title="Recently Modified" subtitle="Timeline and project memory growth">
        <List
          items={[
            ...((dashboard?.recent_timeline ?? []).slice(0, 4).map((item) => `${String(item.type)}: ${String(item.title)}`)),
            `Knowledge growth: ${Number(dashboard?.knowledge_growth?.research_assets ?? 0)} assets`,
            `Fallback assets loaded: ${assets.length}`,
          ]}
        />
      </Panel>
    </section>
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
