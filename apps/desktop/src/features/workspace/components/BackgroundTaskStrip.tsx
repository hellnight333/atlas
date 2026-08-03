import { useMemo } from 'react'

import { Button, Dock } from '../../../components'
import { useActivityStore, useUIStore } from '../../../stores'

const ACTIVE_STATES = new Set(['running', 'blocked'])

export function BackgroundTaskStrip() {
  // Select the array, then narrow it here. Filtering *inside* the selector
  // returns a new array on every call, and a Zustand selector is the
  // `getSnapshot` for `useSyncExternalStore`: React compares the value it read
  // during render with the one it reads at commit, sees two different arrays,
  // and re-renders to catch up — forever. That is React error #185, "Maximum
  // update depth exceeded", and it took down the whole application the instant
  // the workspace rendered.
  //
  // `state.jobs` is a stable reference until the store actually changes, so
  // this subscribes correctly and the filtering happens where it belongs.
  const allJobs = useActivityStore((state) => state.jobs)
  const setActivityCenterOpen = useUIStore((state) => state.setActivityCenterOpen)

  const jobs = useMemo(() => allJobs.filter((job) => ACTIVE_STATES.has(job.state)), [allJobs])

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
