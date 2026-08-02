import { ActivityCard, Button } from '../../../components'
import { useActivityStore, useUIStore } from '../../../stores'

export function ActivityCenterDrawer() {
  const open = useUIStore((state) => state.activityCenterOpen)
  const setOpen = useUIStore((state) => state.setActivityCenterOpen)
  const jobs = useActivityStore((state) => state.jobs)

  if (!open) {
    return null
  }

  return (
    <section className="fixed inset-0 z-40 bg-slate-950/60 backdrop-blur-sm">
      <div className="absolute right-0 top-0 h-full w-full max-w-3xl border-l border-slate-700 bg-slate-950 p-4">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Activity Center</h2>
          <Button onClick={() => setOpen(false)}>Close</Button>
        </div>
        <div className="mb-3 grid gap-2 md:grid-cols-4">
          {['All', 'Running', 'Failures', 'Warnings'].map((filter) => (
            <Button key={filter}>{filter}</Button>
          ))}
        </div>
        <div className="space-y-2 overflow-y-auto pr-1">
          {jobs.map((job) => (
            <ActivityCard key={job.id} job={job} />
          ))}
        </div>
      </div>
    </section>
  )
}
