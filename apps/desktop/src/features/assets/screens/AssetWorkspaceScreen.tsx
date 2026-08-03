import { useParams } from 'react-router-dom'

import { Panel } from '../../../components'
import { useAssetStore } from '../../../stores'

export function AssetWorkspaceScreen() {
  const { id } = useParams()
  const asset = useAssetStore((state) => state.assets.find((candidate) => candidate.id === id) ?? state.assets[0])

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[1.4fr_1fr]">
      <Panel title="Asset Viewer" subtitle={`${asset?.title ?? 'Asset'} · primary asset view with compare options`}>
        <List items={[
          `Type: ${asset?.type ?? 'Unknown'}`,
          `Preview URI: ${asset?.uri ?? 'Unavailable'}`,
          `Version: ${asset?.version ?? 1}`,
          'Publishing readiness',
        ]} />
      </Panel>
      <Panel title="Metadata + Relationships" subtitle="Origin, dependencies, references">
        <List items={[
          `File size: ${asset?.fileSize ?? 'Unknown'}`,
          `MIME: ${asset?.mimeType ?? 'Unknown'}`,
          `Hash: ${asset?.contentHash ?? 'Pending'}`,
          `Tags: ${(asset?.tags ?? []).join(', ') || 'None'}`,
        ]} />
      </Panel>
      <Panel title="AI Analysis" subtitle="Quality, anomaly, and optimization hints">
        <List items={['Missing metadata detected', 'Relationship confidence 0.82', 'Publishing checklist incomplete']} />
      </Panel>
      <Panel title="Version Timeline" subtitle="Checkpoint history with rollback links">
        <List items={[`v${asset?.version ?? 1} - Imported`, `Created: ${asset?.createdAt ?? 'Unknown'}`, `Updated: ${asset?.updatedAt ?? 'Unknown'}`]} />
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
