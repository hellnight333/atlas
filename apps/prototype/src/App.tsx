import { useEffect, useMemo, type ReactNode } from 'react'

import { usePrototypeStore, prototypeData } from './store/usePrototypeStore'
import type { CommandMode, ScreenId, Severity } from './types'

const severityClass: Record<Severity, string> = {
  info: 'bg-sky-500/15 text-sky-300 border-sky-400/40',
  attention: 'bg-indigo-500/15 text-indigo-300 border-indigo-400/40',
  warning: 'bg-amber-500/15 text-amber-300 border-amber-400/40',
  critical: 'bg-rose-600/20 text-rose-200 border-rose-400/60',
}

function App() {
  const activeScreen = usePrototypeStore((state) => state.activeScreen)
  const missionControlOpen = usePrototypeStore((state) => state.missionControlOpen)
  const commandPaletteOpen = usePrototypeStore((state) => state.commandPaletteOpen)
  const activityCenterOpen = usePrototypeStore((state) => state.activityCenterOpen)
  const inspectorOpen = usePrototypeStore((state) => state.inspectorOpen)
  const notifications = usePrototypeStore((state) => state.notifications)

  const navigate = usePrototypeStore((state) => state.navigate)
  const toggleMissionControl = usePrototypeStore((state) => state.toggleMissionControl)
  const toggleCommandPalette = usePrototypeStore((state) => state.toggleCommandPalette)
  const toggleActivityCenter = usePrototypeStore((state) => state.toggleActivityCenter)
  const toggleInspector = usePrototypeStore((state) => state.toggleInspector)

  const runningJobs = prototypeData.jobs.filter((job) => job.state === 'running' || job.state === 'blocked')
  const criticalCount = notifications.filter((item) => item.severity === 'critical').length

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const metaOrCtrl = event.metaKey || event.ctrlKey
      if (metaOrCtrl && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        toggleCommandPalette(true)
      }
      if (metaOrCtrl && event.key.toLowerCase() === 'm') {
        event.preventDefault()
        toggleMissionControl(true)
      }
      if (event.key === 'Escape') {
        toggleCommandPalette(false)
        toggleMissionControl(false)
        toggleActivityCenter(false)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [toggleActivityCenter, toggleCommandPalette, toggleMissionControl])

  return (
    <div className="relative min-h-screen bg-slate-950 text-slate-100">
      <TopBar
        onOpenMission={() => toggleMissionControl(true)}
        onOpenCommand={() => toggleCommandPalette(true)}
        onOpenActivity={() => toggleActivityCenter(true)}
      />

      <div className="grid min-h-[calc(100vh-88px)] grid-cols-1 lg:grid-cols-[270px_1fr_auto]">
        <Sidebar activeScreen={activeScreen} onNavigate={navigate} />

        <main className="flex min-w-0 flex-col border-x border-slate-800 bg-slate-900/60">
          <ScreenHeader activeScreen={activeScreen} />
          <ScreenContent activeScreen={activeScreen} />

          <section className="border-t border-slate-800 bg-slate-900/80 px-4 py-3">
            <div className="mb-2 flex items-center justify-between text-xs uppercase tracking-widest text-slate-400">
              <span>Background Task Strip</span>
              <button
                type="button"
                className="rounded border border-slate-700 px-2 py-1 text-[11px] text-slate-300 hover:border-slate-500"
                onClick={() => toggleActivityCenter(true)}
              >
                Open Activity Center
              </button>
            </div>
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
              {runningJobs.map((job) => (
                <div key={job.id} className="rounded border border-slate-700 bg-slate-950/70 p-2">
                  <p className="truncate text-sm font-medium">{job.name}</p>
                  <div className="mt-1 flex items-center justify-between text-xs text-slate-400">
                    <span className="capitalize">{job.state}</span>
                    <span>{job.elapsed}</span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-800">
                    <div className="h-full bg-cyan-400" style={{ width: `${job.progress}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </section>
        </main>

        {inspectorOpen ? <InspectorPanel onClose={toggleInspector} /> : <InspectorCollapsed onOpen={toggleInspector} />}
      </div>

      <StatusBar
        runningJobs={runningJobs.length}
        criticalCount={criticalCount}
        onOpenActivity={() => toggleActivityCenter(true)}
      />

      <NotificationStack items={notifications} />

      {activityCenterOpen ? <ActivityDrawer onClose={() => toggleActivityCenter(false)} /> : null}
      {missionControlOpen ? <MissionControlOverlay onClose={() => toggleMissionControl(false)} onNavigate={navigate} /> : null}
      {commandPaletteOpen ? <CommandPalette onClose={() => toggleCommandPalette(false)} /> : null}
    </div>
  )
}

type TopBarProps = {
  onOpenMission: () => void
  onOpenCommand: () => void
  onOpenActivity: () => void
}

function TopBar({ onOpenMission, onOpenCommand, onOpenActivity }: TopBarProps) {
  return (
    <header className="flex h-12 items-center justify-between border-b border-slate-800 bg-slate-950 px-4">
      <div className="flex items-center gap-3 text-sm">
        <span className="rounded bg-cyan-500/10 px-2 py-1 text-cyan-300">Tenant: Atlas Labs</span>
        <span className="text-slate-300">Space: Creative Ops</span>
        <span className="text-slate-500">/</span>
        <span className="text-slate-300">Project: Aurora Launch Film</span>
      </div>
      <div className="flex items-center gap-2 text-xs">
        <button type="button" className="rounded border border-slate-700 px-3 py-1 text-slate-300" onClick={onOpenMission}>
          Mission Control
        </button>
        <button type="button" className="rounded border border-slate-700 px-3 py-1 text-slate-300" onClick={onOpenCommand}>
          Command Palette
        </button>
        <button type="button" className="rounded border border-slate-700 px-3 py-1 text-slate-300" onClick={onOpenActivity}>
          Activity
        </button>
      </div>
    </header>
  )
}

function ScreenHeader({ activeScreen }: { activeScreen: ScreenId }) {
  const label = prototypeData.screens.find((screen) => screen.id === activeScreen)?.title ?? 'Workspace'
  return (
    <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900 px-4 py-3">
      <div>
        <h1 className="text-lg font-semibold text-slate-100">{label}</h1>
        <p className="text-sm text-slate-400">Blueprint-aligned interactive prototype with mocked state</p>
      </div>
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <span className="rounded border border-slate-700 px-2 py-1">Cmd/Ctrl+K</span>
        <span className="rounded border border-slate-700 px-2 py-1">Cmd/Ctrl+M</span>
      </div>
    </div>
  )
}

type SidebarProps = {
  activeScreen: ScreenId
  onNavigate: (screen: ScreenId) => void
}

function Sidebar({ activeScreen, onNavigate }: SidebarProps) {
  return (
    <aside className="border-b border-slate-800 bg-slate-950 lg:border-b-0 lg:border-r">
      <div className="border-b border-slate-800 px-4 py-3 text-xs uppercase tracking-widest text-slate-500">Sidebar</div>
      <nav className="grid gap-1 p-3">
        {prototypeData.screens.map((screen) => {
          const active = screen.id === activeScreen
          return (
            <button
              key={screen.id}
              type="button"
              onClick={() => onNavigate(screen.id)}
              className={`rounded px-3 py-2 text-left text-sm transition ${
                active
                  ? 'bg-cyan-500/20 text-cyan-200 ring-1 ring-cyan-500/40'
                  : 'text-slate-300 hover:bg-slate-800'
              }`}
            >
              {screen.title}
            </button>
          )
        })}
      </nav>

      <div className="border-t border-slate-800 p-3">
        <p className="mb-2 text-xs uppercase tracking-widest text-slate-500">Studios</p>
        <div className="space-y-1 text-sm text-slate-300">
          {prototypeData.studios.slice(0, 6).map((studio) => (
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

function ScreenContent({ activeScreen }: { activeScreen: ScreenId }) {
  switch (activeScreen) {
    case 'desktop-overview':
      return <DesktopOverviewScreen />
    case 'home-workspace':
      return <HomeWorkspaceScreen />
    case 'project-workspace':
      return <ProjectWorkspaceScreen />
    case 'studio-workspace':
      return <StudioWorkspaceScreen />
    case 'asset-workspace':
      return <AssetWorkspaceScreen />
    case 'mission-control':
      return <MissionControlPreviewScreen />
    case 'command-palette':
      return <CommandPalettePreviewScreen />
    case 'activity-center':
      return <ActivityCenterPreviewScreen />
    default:
      return <DesktopOverviewScreen />
  }
}

function DesktopOverviewScreen() {
  return (
    <section className="grid flex-1 gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">
      <Surface title="Top Bar" subtitle="Scope identity, search entry, command entry" />
      <Surface title="Sidebar" subtitle="Core navigation + studio taxonomy projection" />
      <Surface title="Workspace" subtitle="Primary production region with split views" />
      <Surface title="Inspector" subtitle="Properties, metadata, relationships, versions" />
      <Surface title="Status Bar" subtitle="Ambient telemetry domains only" />
      <Surface title="Activity + Notifications" subtitle="Lifecycle history + escalation routing" />
    </section>
  )
}

function HomeWorkspaceScreen() {
  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-3">
      <Surface title="Continue Working" subtitle="Resume interrupted contexts">
        <MiniList items={prototypeData.projects.map((project) => `${project.name} (${project.progress}%)`)} />
      </Surface>
      <Surface title="Pinned Projects" subtitle="User-curated anchors">
        <MiniList items={['Aurora Launch Film', 'Atlas SaaS Narrative', 'Enterprise Playbook']} />
      </Surface>
      <Surface title="AI Suggestions" subtitle="Next best actions">
        <MiniList
          items={[
            'Resolve blocked source approval in Atlas SaaS Narrative',
            'Review completed rendering outputs for Aurora Launch Film',
          ]}
        />
      </Surface>
      <Surface title="Recent Assets" subtitle="Most recently touched outputs">
        <MiniList items={prototypeData.assets.map((asset) => asset.title)} />
      </Surface>
      <Surface title="Recent Sessions" subtitle="Timeline of previous sessions">
        <MiniList items={['Today 09:12 - 10:48', 'Yesterday 14:05 - 18:40', 'Yesterday 09:15 - 12:01']} />
      </Surface>
      <Surface title="Activity Summary" subtitle="Running, blocked, warning, critical counts">
        <MiniList items={['Running: 2', 'Blocked: 1', 'Warnings: 2', 'Critical: 1']} />
      </Surface>
    </section>
  )
}

function ProjectWorkspaceScreen() {
  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[1.2fr_1fr]">
      <Surface title="Workspace + Files + Assets" subtitle="Active project board with split tabs">
        <MiniList items={['Files', 'Assets', 'Timeline', 'Studios', 'Project Overview']} />
      </Surface>
      <Surface title="History + Versioning" subtitle="Checkpoint strip and compare entry points">
        <MiniList items={['Checkpoint A - Passed QA', 'Checkpoint B - Pending review', 'Checkpoint C - Branch draft']} />
      </Surface>
      <Surface title="Collaboration Placeholder" subtitle="Presence and ownership markers">
        <p className="text-xs text-slate-400">TODO: Finalize real-time collaboration and role arbitration flow.</p>
      </Surface>
      <Surface title="Project Activity" subtitle="Project-scoped running and failed jobs">
        <MiniList items={prototypeData.jobs.map((job) => `${job.name} - ${job.state}`)} />
      </Surface>
    </section>
  )
}

function StudioWorkspaceScreen() {
  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[1.4fr_1fr]">
      <Surface title="Studio Toolbar + Canvas" subtitle="Workflow stage controls and main production surface">
        <MiniList items={['Toolbar', 'Canvas', 'Preview', 'History strip']} />
      </Surface>
      <Surface title="Parameters + Inspector" subtitle="Contextual controls and AI quality cues">
        <MiniList items={['Parameters', 'Metadata', 'AI suggestions', 'Diagnostics']} />
      </Surface>
      <Surface title="Assets Rail" subtitle="Inputs and outputs for active studio workflow">
        <MiniList items={prototypeData.assets.slice(0, 4).map((asset) => asset.title)} />
      </Surface>
      <Surface title="Background Tasks" subtitle="Running, blocked, retryable states">
        <MiniList items={prototypeData.jobs.map((job) => `${job.domain} - ${job.progress}%`)} />
      </Surface>
    </section>
  )
}

function AssetWorkspaceScreen() {
  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[1.4fr_1fr]">
      <Surface title="Asset Viewer" subtitle="Primary asset view with compare options">
        <MiniList items={['Viewer', 'Compare mode', 'Annotations', 'Publishing readiness']} />
      </Surface>
      <Surface title="Metadata + Relationships" subtitle="Origin, dependencies, references">
        <MiniList items={['Ownership context', 'Version history', 'References', 'Tags']} />
      </Surface>
      <Surface title="AI Analysis" subtitle="Quality, anomaly, and optimization hints">
        <MiniList items={['Missing metadata detected', 'Relationship confidence 0.82', 'Publishing checklist incomplete']} />
      </Surface>
      <Surface title="Version Timeline" subtitle="Checkpoint history with rollback links">
        <MiniList items={['v3 - Stable', 'v4 - Pending review', 'v5 - Draft']} />
      </Surface>
    </section>
  )
}

function MissionControlPreviewScreen() {
  return (
    <section className="grid flex-1 place-items-center p-4">
      <div className="max-w-2xl rounded-lg border border-slate-700 bg-slate-950 p-8 text-center">
        <h2 className="text-xl font-semibold">Mission Control Preview Screen</h2>
        <p className="mt-3 text-sm text-slate-400">
          Use the Mission Control button or Cmd/Ctrl+M to open the full-screen overlay with cross-project orchestration.
        </p>
      </div>
    </section>
  )
}

function CommandPalettePreviewScreen() {
  return (
    <section className="grid flex-1 place-items-center p-4">
      <div className="max-w-2xl rounded-lg border border-slate-700 bg-slate-950 p-8 text-center">
        <h2 className="text-xl font-semibold">Command Palette Preview Screen</h2>
        <p className="mt-3 text-sm text-slate-400">
          Use Cmd/Ctrl+K to open command mode, search mode, quick action mode, and AI suggestion mode.
        </p>
      </div>
    </section>
  )
}

function ActivityCenterPreviewScreen() {
  return (
    <section className="grid flex-1 place-items-center p-4">
      <div className="max-w-2xl rounded-lg border border-slate-700 bg-slate-950 p-8 text-center">
        <h2 className="text-xl font-semibold">Activity Center Preview Screen</h2>
        <p className="mt-3 text-sm text-slate-400">Open Activity from top bar to inspect the timeline, failures, and grouped job domains.</p>
      </div>
    </section>
  )
}

function Surface({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children?: ReactNode
}) {
  return (
    <article className="rounded-lg border border-slate-700 bg-slate-950 p-4">
      <h3 className="text-base font-semibold text-slate-100">{title}</h3>
      <p className="mt-1 text-sm text-slate-400">{subtitle}</p>
      {children ? <div className="mt-3">{children}</div> : null}
    </article>
  )
}

function MiniList({ items }: { items: string[] }) {
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

function InspectorPanel({ onClose }: { onClose: () => void }) {
  const selectedAssetId = usePrototypeStore((state) => state.selectedAssetId)
  const selectedAsset = prototypeData.assets.find((asset) => asset.id === selectedAssetId) ?? prototypeData.assets[0]

  return (
    <aside className="hidden w-[320px] border-l border-slate-800 bg-slate-950/90 lg:flex lg:flex-col">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <h2 className="text-sm font-semibold">Inspector</h2>
        <button type="button" className="rounded border border-slate-700 px-2 py-1 text-xs" onClick={onClose}>
          Collapse
        </button>
      </div>
      <div className="space-y-3 overflow-y-auto p-4 text-sm">
        <Surface title="Selected Object" subtitle={selectedAsset?.title ?? 'No asset selected'} />
        <Surface title="Property Groups" subtitle="Parameters, metadata, tags, quality state" />
        <Surface title="AI Suggestions" subtitle="2 suggestions ready - confidence 0.81" />
        <Surface title="Relationships" subtitle="Upstream 3 · Downstream 5" />
      </div>
    </aside>
  )
}

function InspectorCollapsed({ onOpen }: { onOpen: () => void }) {
  return (
    <aside className="hidden w-[58px] border-l border-slate-800 bg-slate-950 lg:flex lg:items-start lg:justify-center lg:pt-4">
      <button type="button" className="rounded border border-slate-700 px-2 py-1 text-xs" onClick={onOpen}>
        Open
      </button>
    </aside>
  )
}

type StatusBarProps = {
  runningJobs: number
  criticalCount: number
  onOpenActivity: () => void
}

function StatusBar({ runningJobs, criticalCount, onOpenActivity }: StatusBarProps) {
  return (
    <footer className="flex h-10 items-center justify-between border-t border-slate-800 bg-slate-950 px-3 text-xs text-slate-300">
      <div className="flex items-center gap-3">
        <span>Workspace: Aurora Launch Film</span>
        <span>Models: 3</span>
        <span>GPU: Available</span>
        <span>Cloud: Degraded</span>
        <span>Git: Clean</span>
        <span>Sync: Delayed</span>
        <span>Memory: 2.3 GB</span>
      </div>
      <div className="flex items-center gap-3">
        <button type="button" className="rounded border border-slate-700 px-2 py-1" onClick={onOpenActivity}>
          Running Jobs: {runningJobs}
        </button>
        <span className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-rose-300">
          Notifications: {criticalCount}
        </span>
      </div>
    </footer>
  )
}

function NotificationStack({ items }: { items: Array<{ id: string; title: string; detail: string; severity: Severity }> }) {
  return (
    <section className="pointer-events-none fixed right-4 top-16 z-30 hidden w-[340px] space-y-2 xl:block">
      {items.slice(0, 3).map((item) => (
        <div key={item.id} className={`rounded border p-3 shadow-lg ${severityClass[item.severity]}`}>
          <p className="text-sm font-semibold">{item.title}</p>
          <p className="mt-1 text-xs opacity-90">{item.detail}</p>
        </div>
      ))}
    </section>
  )
}

function ActivityDrawer({ onClose }: { onClose: () => void }) {
  return (
    <section className="fixed inset-0 z-40 bg-slate-950/60 backdrop-blur-sm">
      <div className="absolute right-0 top-0 h-full w-full max-w-3xl border-l border-slate-700 bg-slate-950 p-4">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Activity Center</h2>
          <button type="button" className="rounded border border-slate-700 px-3 py-1 text-sm" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="mb-3 grid gap-2 md:grid-cols-4">
          {['All', 'Running', 'Failures', 'Warnings'].map((filter) => (
            <button key={filter} type="button" className="rounded border border-slate-700 px-3 py-2 text-sm text-slate-300">
              {filter}
            </button>
          ))}
        </div>
        <div className="space-y-2 overflow-y-auto pr-1">
          {prototypeData.jobs.map((job) => (
            <article key={job.id} className="rounded border border-slate-700 bg-slate-900 p-3">
              <div className="flex items-center justify-between">
                <p className="font-medium">{job.name}</p>
                <span className={`rounded border px-2 py-0.5 text-xs ${severityClass[job.severity]}`}>{job.severity}</span>
              </div>
              <p className="mt-1 text-sm text-slate-400">
                {job.domain} · {job.state} · elapsed {job.elapsed}
              </p>
              <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-800">
                <div className="h-full bg-cyan-400" style={{ width: `${job.progress}%` }} />
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}

type MissionControlOverlayProps = {
  onClose: () => void
  onNavigate: (screen: ScreenId) => void
}

function MissionControlOverlay({ onClose, onNavigate }: MissionControlOverlayProps) {
  return (
    <section className="fixed inset-0 z-50 bg-slate-950/95 p-6 text-slate-100">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold">Mission Control</h2>
          <p className="text-sm text-slate-400">What you are working on, what agents are doing, and what to do next.</p>
        </div>
        <button type="button" className="rounded border border-slate-600 px-3 py-1 text-sm" onClick={onClose}>
          Exit
        </button>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Surface title="Active Projects" subtitle="Current mission load by status">
          <MiniList
            items={prototypeData.projects.map((project) => `${project.name} · ${project.status} · ${project.progress}%`)}
          />
        </Surface>
        <Surface title="Running Agents" subtitle="Live agent operations">
          <MiniList
            items={prototypeData.agentTasks.map(
              (task) => `${task.name} · ${task.status} · conf ${(task.confidence * 100).toFixed(0)}%`,
            )}
          />
        </Surface>
        <Surface title="Suggested Next Actions" subtitle="Explainable recommendations">
          <MiniList
            items={[
              'Resolve blocked research dependency in Atlas SaaS Narrative',
              'Approve latest rendering outputs for Aurora Launch Film',
              'Open Activity Center failures lane and run recoverable retries',
            ]}
          />
        </Surface>

        <Surface title="Recent Assets" subtitle="Most recently generated artifacts">
          <MiniList items={prototypeData.assets.map((asset) => `${asset.title} · ${asset.type}`)} />
        </Surface>
        <Surface title="Recent History" subtitle="Cross-project trajectory">
          <MiniList items={['09:12 Mission started', '09:18 Research task blocked', '09:34 Rendering batch at 64%']} />
        </Surface>
        <Surface title="Current Workspace" subtitle="Fast context routing">
          <div className="grid gap-2">
            <button
              type="button"
              className="rounded border border-slate-700 px-3 py-2 text-left text-sm"
              onClick={() => {
                onNavigate('project-workspace')
                onClose()
              }}
            >
              Jump to Project Workspace
            </button>
            <button
              type="button"
              className="rounded border border-slate-700 px-3 py-2 text-left text-sm"
              onClick={() => {
                onNavigate('studio-workspace')
                onClose()
              }}
            >
              Jump to Studio Workspace
            </button>
            <button
              type="button"
              className="rounded border border-slate-700 px-3 py-2 text-left text-sm"
              onClick={() => {
                onNavigate('activity-center')
                onClose()
              }}
            >
              Jump to Activity Center Screen
            </button>
          </div>
        </Surface>
      </div>
    </section>
  )
}

function CommandPalette({ onClose }: { onClose: () => void }) {
  const commandMode = usePrototypeStore((state) => state.commandMode)
  const commandQuery = usePrototypeStore((state) => state.commandQuery)
  const commandHistory = usePrototypeStore((state) => state.commandHistory)
  const pinnedCommands = usePrototypeStore((state) => state.pinnedCommands)

  const setCommandMode = usePrototypeStore((state) => state.setCommandMode)
  const setCommandQuery = usePrototypeStore((state) => state.setCommandQuery)
  const runCommand = usePrototypeStore((state) => state.runCommand)

  const filtered = useMemo(() => {
    const q = commandQuery.trim().toLowerCase()
    if (!q) {
      return prototypeData.commands
    }
    return prototypeData.commands.filter((command) => command.label.toLowerCase().includes(q))
  }, [commandQuery])

  const historyCommands = prototypeData.commands.filter((command) => commandHistory.includes(command.id))
  const pinnedCommandItems = prototypeData.commands.filter((command) => pinnedCommands.includes(command.id))

  return (
    <section className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/60 p-6 backdrop-blur-sm">
      <div className="w-full max-w-4xl rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
          <h2 className="text-sm font-semibold">Command Palette</h2>
          <button type="button" className="rounded border border-slate-700 px-2 py-1 text-xs" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="border-b border-slate-700 px-4 py-3">
          <div className="mb-3 flex flex-wrap gap-2">
            {(['command', 'search', 'quick-action', 'ai'] as CommandMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                className={`rounded border px-3 py-1 text-xs ${
                  commandMode === mode
                    ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                    : 'border-slate-700 text-slate-300'
                }`}
                onClick={() => setCommandMode(mode)}
              >
                {mode}
              </button>
            ))}
          </div>
          <input
            value={commandQuery}
            onChange={(event) => setCommandQuery(event.target.value)}
            placeholder="Type command, search query, or natural language intent"
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none ring-cyan-500/40 focus:ring"
            autoFocus
          />
          <p className="mt-2 text-xs text-slate-400">
            TODO: Final command alias conflict precedence across plugin namespaces is intentionally deferred.
          </p>
        </div>

        <div className="grid gap-4 p-4 md:grid-cols-3">
          <div>
            <h3 className="mb-2 text-xs uppercase tracking-widest text-slate-500">Candidates</h3>
            <div className="space-y-1">
              {filtered.map((command) => (
                <button
                  key={command.id}
                  type="button"
                  className="block w-full rounded border border-slate-700 bg-slate-950 px-2 py-2 text-left text-sm hover:border-slate-500"
                  onClick={() => runCommand(command.id)}
                >
                  <p>{command.label}</p>
                  <p className="text-xs text-slate-500">
                    {command.kind} · {command.scope}
                  </p>
                </button>
              ))}
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-xs uppercase tracking-widest text-slate-500">Recent Commands</h3>
            <MiniList items={historyCommands.map((command) => command.label)} />
          </div>

          <div>
            <h3 className="mb-2 text-xs uppercase tracking-widest text-slate-500">Pinned Commands + AI Hints</h3>
            <MiniList items={pinnedCommandItems.map((command) => command.label)} />
            <div className="mt-2 rounded border border-slate-700 bg-slate-950 p-2 text-xs text-slate-400">
              AI Suggestion: Run Publish Checklist after resolving blocked research dependency.
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

export default App
