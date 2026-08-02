import { Button } from '../../../components'

type AppStatusBarProps = {
  runningJobs: number
  criticalCount: number
  onOpenActivity: () => void
}

export function AppStatusBar({ runningJobs, criticalCount, onOpenActivity }: AppStatusBarProps) {
  return (
    <footer className="flex h-10 items-center justify-between border-t border-slate-800 bg-slate-950 px-3 text-xs text-slate-300">
      <div className="flex items-center gap-3 overflow-x-auto">
        <span>Workspace: Aurora Launch Film</span>
        <span>Models: 3</span>
        <span>GPU: Available</span>
        <span>Cloud: Degraded</span>
        <span>Git: Clean</span>
        <span>Sync: Delayed</span>
        <span>Memory: 2.3 GB</span>
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={onOpenActivity}>Running Jobs: {runningJobs}</Button>
        <span className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-rose-300">
          Notifications: {criticalCount}
        </span>
      </div>
    </footer>
  )
}
