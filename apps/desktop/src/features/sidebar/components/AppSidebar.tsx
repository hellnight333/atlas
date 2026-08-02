import { SidebarItem } from '../../../components'
import { useWorkspaceStore } from '../../../stores'

const items = [
  { label: 'Desktop Overview', to: '/' },
  { label: 'Home Workspace', to: '/workspace' },
  { label: 'Project Workspace', to: '/project/p1' },
  { label: 'Chat Studio', to: '/project/p1/chat' },
  { label: 'Studio Workspace', to: '/studio/s1' },
  { label: 'Asset Workspace', to: '/asset/a1' },
  { label: 'Image Studio', to: '/image-studio' },
  { label: 'Research', to: '/research' },
  { label: 'Review', to: '/review' },
  { label: 'Agent Studio', to: '/agent-studio' },
  { label: 'Automation Studio', to: '/automation' },
  { label: 'Approval Center', to: '/approvals' },
  { label: 'Cluster Studio', to: '/cluster' },
  { label: 'Mission Control', to: '/mission-control' },
  { label: 'Activity Center', to: '/activity-center' },
]

export function AppSidebar() {
  const studios = useWorkspaceStore((state) => state.studios)

  return (
    <aside className="border-b border-slate-800 bg-slate-950 lg:border-b-0 lg:border-r">
      <div className="border-b border-slate-800 px-4 py-3 text-xs uppercase tracking-widest text-slate-500">Sidebar</div>
      <nav className="grid gap-1 p-3">
        {items.map((item) => (
          <SidebarItem key={item.to} label={item.label} to={item.to} />
        ))}
      </nav>
      <div className="border-t border-slate-800 p-3">
        <p className="mb-2 text-xs uppercase tracking-widest text-slate-500">Studios</p>
        <div className="space-y-1 text-sm text-slate-300">
          {studios.slice(0, 6).map((studio) => (
            <div key={studio.id} className="rounded bg-slate-900 px-2 py-1">
              <div className="flex items-center justify-between">
                <span>{studio.name}</span>
                <span className="text-xs text-slate-500">{studio.kind}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </aside>
  )
}
