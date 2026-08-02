import { useEffect } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { Button, Notification } from '../components'
import { OrganizationSwitcher } from '../features/organization/components/OrganizationSwitcher'
import { AppSidebar } from '../features/sidebar/components/AppSidebar'
import { AppStatusBar } from '../features/status-bar/components/AppStatusBar'
import { ActivityCenterDrawer } from '../features/activity/components/ActivityCenterDrawer'
import { CommandPaletteOverlay } from '../features/command-palette/components/CommandPaletteOverlay'
import { InspectorPanel } from '../features/inspector/components/InspectorPanel'
import { MissionControlOverlay } from '../features/mission-control/components/MissionControlOverlay'
import { BackgroundTaskStrip } from '../features/workspace/components/BackgroundTaskStrip'
import { WorkspaceHeader } from '../features/workspace/components/WorkspaceHeader'
import { useActivityStore, useCommandPaletteStore, useMissionControlStore, useNotificationStore, useUIStore } from '../stores'

const routeLabels: Record<string, string> = {
  '/': 'Desktop Overview',
  '/workspace': 'Home Workspace',
  '/research': 'Research Workspace',
  '/image-studio': 'Image Studio',
  '/workflow-studio': 'Workflow Studio',
  '/mission-control': 'Mission Control',
  '/activity-center': 'Activity Center',
}

export function DesktopShellLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const jobs = useActivityStore((state) => state.jobs)
  const notifications = useNotificationStore((state) => state.notifications)
  const setActivityCenterOpen = useUIStore((state) => state.setActivityCenterOpen)
  const setCommandPaletteOpen = useCommandPaletteStore((state) => state.setOpen)
  const setMissionControlOpen = useMissionControlStore((state) => state.setOpen)

  const runningJobs = jobs.filter((job) => job.state === 'running' || job.state === 'blocked')
  const criticalCount = notifications.filter((item) => item.severity === 'critical').length

  const title = routeLabels[location.pathname] ?? resolveDynamicLabel(location.pathname)

  useEffect(() => {
    setMissionControlOpen(location.pathname === '/mission-control')
  }, [location.pathname, setMissionControlOpen])

  return (
    <div className="relative min-h-screen bg-slate-950 text-slate-100">
      <header className="flex h-12 items-center justify-between border-b border-slate-800 bg-slate-950 px-4">
        <div className="flex items-center gap-3 text-sm">
          <OrganizationSwitcher />
          <span className="text-slate-500">/</span>
          <span className="text-slate-300">Project: Aurora Launch Film</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <Button onClick={() => navigate('/mission-control')}>Mission Control</Button>
          <Button onClick={() => setCommandPaletteOpen(true)}>Command Palette</Button>
          <Button onClick={() => setActivityCenterOpen(true)}>Activity</Button>
        </div>
      </header>

      <div className="grid min-h-[calc(100vh-88px)] grid-cols-1 lg:grid-cols-[270px_1fr_auto]">
        <AppSidebar />

        <main className="flex min-w-0 flex-col border-x border-slate-800 bg-slate-900/60">
          <WorkspaceHeader
            title={title}
            subtitle="Production-ready frontend foundation preserving the validated prototype UX"
            actions={
              <>
                <span className="rounded border border-slate-700 px-2 py-1">Cmd/Ctrl+K</span>
                <span className="rounded border border-slate-700 px-2 py-1">Cmd/Ctrl+M</span>
              </>
            }
          />
          <Outlet />
          <BackgroundTaskStrip />
        </main>

        <InspectorPanel />
      </div>

      <AppStatusBar runningJobs={runningJobs.length} criticalCount={criticalCount} onOpenActivity={() => setActivityCenterOpen(true)} />

      <section className="pointer-events-none fixed right-4 top-16 z-30 hidden w-[340px] space-y-2 xl:block">
        {notifications.slice(0, 3).map((notification) => (
          <Notification key={notification.id} notification={notification} />
        ))}
      </section>

      <ActivityCenterDrawer />
      <MissionControlOverlay />
      <CommandPaletteOverlay />
    </div>
  )
}

function resolveDynamicLabel(pathname: string): string {
  if (pathname.startsWith('/project/')) {
    return 'Project Workspace'
  }
  if (pathname.startsWith('/asset/')) {
    return 'Asset Workspace'
  }
  if (pathname.startsWith('/studio/')) {
    return 'Studio Workspace'
  }
  return 'Workspace'
}
