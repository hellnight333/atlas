import type { Job } from '../types/domain'

import { StatusIndicator } from './StatusIndicator'

export function ActivityCard({ job }: { job: Job }) {
  return (
    <article className="rounded border border-slate-700 bg-slate-900 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium text-slate-100">{job.name}</p>
        <StatusIndicator severity={job.severity} label={job.severity} />
      </div>
      <p className="mt-1 text-sm text-slate-400">
        {job.domain} · {job.state} · {job.elapsed}
      </p>
      <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-800">
        <div className="h-full bg-cyan-400" style={{ width: `${job.progress}%` }} />
      </div>
    </article>
  )
}
