import { Panel } from '../../../components'
import { useWorkspaceIntelligenceStore } from '../../../stores'

export function DesktopOverviewScreen() {
  const context = useWorkspaceIntelligenceStore((state) => state.context)
  const recommendations = useWorkspaceIntelligenceStore((state) => state.recommendations)

  return (
    <section className="grid flex-1 gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">
      <Panel title="Top Bar" subtitle="Scope identity, search entry, command entry" />
      <Panel title="Sidebar" subtitle="Core navigation plus studio taxonomy projection" />
      <Panel title="Workspace" subtitle="Primary production region with split views" />
      <Panel title="Workspace Intelligence" subtitle="Today's progress, recent assets, and suggested next step">
        <ul className="space-y-1 text-sm text-slate-300">
          <li className="rounded bg-slate-900 px-2 py-1">Today's Progress: {context?.workspace_context?.recent_activity?.length ?? 0} activity items</li>
          <li className="rounded bg-slate-900 px-2 py-1">Recent Assets: {context?.workspace_context?.recent_assets?.length ?? 0}</li>
          <li className="rounded bg-slate-900 px-2 py-1">Continue Working: {(context?.workspace_context?.suggested_tasks ?? []).length} suggested tasks</li>
          <li className="rounded bg-slate-900 px-2 py-1">Suggested Next Step: {recommendations?.recommendations?.[0]?.title ?? 'No recommendation'}</li>
          <li className="rounded bg-slate-900 px-2 py-1">Recent AI Activity: {context?.workspace_context?.recent_conversations?.length ?? 0} conversations</li>
          <li className="rounded bg-slate-900 px-2 py-1">Recently Modified: {context?.workspace_context?.recent_assets?.slice(0, 1).map((item) => String(item.id)).join(', ') || 'none'}</li>
          <li className="rounded bg-slate-900 px-2 py-1">Pinned: {context?.workspace_context?.pinned_assets?.length ?? 0}</li>
          <li className="rounded bg-slate-900 px-2 py-1">Open Reviews: {context?.workspace_context?.recent_reviews?.filter((review) => review.status !== 'published').length ?? 0}</li>
          <li className="rounded bg-slate-900 px-2 py-1">Running Jobs: {context?.workspace_context?.open_tasks?.filter((task) => task.status === 'running').length ?? 0}</li>
        </ul>
      </Panel>
      <Panel title="Inspector" subtitle="Properties, metadata, relationships, versions" />
      <Panel title="Status Bar" subtitle="Ambient telemetry domains only" />
      <Panel title="Activity + Notifications" subtitle="Lifecycle history plus escalation routing" />
    </section>
  )
}
