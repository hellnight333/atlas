import { InspectorSection } from '../../../components'
import { useEffect } from 'react'

import {
  useApprovalStore,
  useAssetStore,
  useWorkspaceIntelligenceStore,
  useWorkspaceStore,
} from '../../../stores'

export function InspectorPanel() {
  const inspectorOpen = useWorkspaceStore((state) => state.inspectorOpen)
  const toggleInspector = useWorkspaceStore((state) => state.toggleInspector)
  const selectedAssetId = useAssetStore((state) => state.selectedAssetId)
  const assets = useAssetStore((state) => state.assets)
  const selectedAsset = assets.find((asset) => asset.id === selectedAssetId)
  const graph = useWorkspaceIntelligenceStore((state) => state.graph)
  const selectedAssetLineage = useWorkspaceIntelligenceStore((state) => state.selectedAssetLineage)
  const loadAssetLineage = useWorkspaceIntelligenceStore((state) => state.loadAssetLineage)

  const approvals = useApprovalStore((state) => state.approvals)
  const approvalHistory = useApprovalStore((state) => state.history)
  const activeApproval = useApprovalStore((state) => state.activeApproval)

  const assetApproval =
    approvals.find((approval) => approval.asset_id && approval.asset_id === selectedAssetId) ??
    activeApproval

  useEffect(() => {
    if (selectedAssetId) {
      void loadAssetLineage(selectedAssetId)
    }
  }, [loadAssetLineage, selectedAssetId])

  if (!inspectorOpen) {
    return (
      <aside className="hidden w-[58px] border-l border-slate-800 bg-slate-950 lg:flex lg:items-start lg:justify-center lg:pt-4">
        <button type="button" className="rounded border border-slate-700 px-2 py-1 text-xs" onClick={toggleInspector}>
          Open
        </button>
      </aside>
    )
  }

  return (
    <aside className="hidden w-[320px] border-l border-slate-800 bg-slate-950/90 lg:flex lg:flex-col">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <h2 className="text-sm font-semibold">Inspector</h2>
        <button type="button" className="rounded border border-slate-700 px-2 py-1 text-xs" onClick={toggleInspector}>
          Collapse
        </button>
      </div>
      <div className="space-y-3 overflow-y-auto p-4 text-sm">
        <InspectorSection title="Selected Object">{selectedAsset?.title ?? 'No asset selected'}</InspectorSection>
        <InspectorSection title="Property Groups">Parameters, metadata, tags, quality state</InspectorSection>
        <InspectorSection title="AI Suggestions">2 suggestions ready · confidence 0.81</InspectorSection>
        <InspectorSection title="Approval">
          {assetApproval ? (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs uppercase tracking-widest text-slate-500">Status</span>
                <span
                  className={`text-xs uppercase tracking-widest ${APPROVAL_STATE_STYLES[assetApproval.state] ?? 'text-slate-400'}`}
                >
                  {assetApproval.state}
                </span>
              </div>
              <InspectorRow
                label="Waiting Reason"
                value={assetApproval.reason || 'No reason recorded'}
              />
              <InspectorRow
                label="Policy Source"
                value={assetApproval.policy_name ?? 'No policy'}
              />
              <InspectorRow
                label="Required Approvers"
                value={assetApproval.required_approvers.join(', ') || 'Any operator'}
              />
              <InspectorRow
                label="Quorum"
                value={`${assetApproval.decisions.filter((d) => d.decision === 'approve').length} of ${assetApproval.approvals_required}`}
              />
              <div>
                <div className="text-xs uppercase tracking-widest text-slate-500">
                  Decision History
                </div>
                {approvalHistory.length === 0 ? (
                  <div className="mt-1 text-xs text-slate-400">No decisions recorded</div>
                ) : (
                  <ul className="mt-1 space-y-1">
                    {approvalHistory.slice(0, 5).map((event) => (
                      <li key={event.id} className="text-xs text-slate-400">
                        <span className="text-slate-300">{event.event_type}</span> · {event.actor}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          ) : (
            <div className="text-xs text-slate-400">No approval required for this object</div>
          )}
        </InspectorSection>
        <InspectorSection title="Relationships">
          <div>Parents / Children / Related Objects</div>
          <div className="mt-2 text-xs text-slate-400">Project Nodes: {graph?.graph.nodes.length ?? 0}</div>
          <div className="mt-1 text-xs text-slate-400">Project Edges: {graph?.graph.edges.length ?? 0}</div>
          <div className="mt-1 text-xs text-slate-400">Lineage Nodes: {selectedAssetLineage?.nodes.length ?? 0}</div>
          <div className="mt-1 text-xs text-slate-400">Lineage Edges: {selectedAssetLineage?.edges.length ?? 0}</div>
        </InspectorSection>
      </div>
    </aside>
  )
}

const APPROVAL_STATE_STYLES: Record<string, string> = {
  pending: 'text-amber-300',
  approved: 'text-emerald-300',
  rejected: 'text-rose-300',
  cancelled: 'text-slate-400',
  expired: 'text-slate-500',
}

function InspectorRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-0.5 text-xs text-slate-300">{value}</div>
    </div>
  )
}
