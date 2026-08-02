import { ActivityCard, Panel } from '../../../components'
import { useActivityStore } from '../../../stores'

export function ActivityCenterScreen() {
  const jobs = useActivityStore((state) => state.jobs)

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[1.2fr_1fr]">
      <Panel title="Activity Timeline" subtitle="Running, blocked, warning, and failure records">
        <div className="space-y-2">
          {jobs.map((job) => (
            <ActivityCard key={job.id} job={job} />
          ))}
        </div>
      </Panel>
      <Panel title="Domain Groups" subtitle="Rendering, research, training, publishing, downloads, uploads">
        <ul className="space-y-1 text-sm text-slate-300">
          <li>Rendering</li>
          <li>Research</li>
          <li>Training</li>
          <li>Publishing</li>
          <li>Downloads</li>
          <li>Uploads</li>
        </ul>
      </Panel>
    </section>
  )
}
