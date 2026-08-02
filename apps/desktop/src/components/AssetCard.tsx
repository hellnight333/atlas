import type { Asset } from '../types/domain'

import { Panel } from './Panel'

export function AssetCard({ asset }: { asset: Asset }) {
  return (
    <Panel title={asset.title} subtitle={`${asset.type} · ${asset.freshness}`}>
      <div className="text-sm text-slate-300">Project {asset.projectId}</div>
    </Panel>
  )
}
