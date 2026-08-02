import { Button, Dock } from '../../../components'
import { useActivityStore, useUIStore } from '../../../stores'

export function BackgroundTaskStrip() {
  const jobs = useActivityStore((state) => state.jobs.filter((job) => job.state === 'running' || job.state === 'blocked'))
  const setActivityCenterOpen = useUIStore((state) => state.setActivityCenterOpen)

  return (
    <Dock title="Background Task Strip" action={<Button onClick={() => setActivityCenterOpen(true)}>Open Activity Center</Button>}>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {jobs.map((job) => (
          <div key={job.id} className="rounded border border-slate-700 bg-slate-950/70 p-2">
            <p className="truncate text-sm font-medium text-slate-100">{job.name}</p>
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
    </Dock>
  )
}
