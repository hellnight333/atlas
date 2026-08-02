import { useParams } from 'react-router-dom'

import { Panel } from '../../../components'
import { useActivityStore, useAssetStore } from '../../../stores'

export function StudioWorkspaceScreen() {
  const { id } = useParams()
  const assets = useAssetStore((state) => state.assets)
  const jobs = useActivityStore((state) => state.jobs)

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[1.4fr_1fr]">
      <Panel title="Studio Toolbar + Canvas" subtitle={`Studio ${id ?? 's1'} · workflow stage controls and main production surface`}>
        <List items={['Toolbar', 'Canvas', 'Preview', 'History strip']} />
      </Panel>
      <Panel title="Parameters + Inspector" subtitle="Contextual controls and AI quality cues">
        <List items={['Parameters', 'Metadata', 'AI suggestions', 'Diagnostics']} />
      </Panel>
      <Panel title="Assets Rail" subtitle="Inputs and outputs for active studio workflow">
        <List items={assets.slice(0, 4).map((asset) => asset.title)} />
      </Panel>
      <Panel title="Background Tasks" subtitle="Running, blocked, retryable states">
        <List items={jobs.map((job) => `${job.domain} - ${job.progress}%`)} />
      </Panel>
    </section>
  )
}

function List({ items }: { items: string[] }) {
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
