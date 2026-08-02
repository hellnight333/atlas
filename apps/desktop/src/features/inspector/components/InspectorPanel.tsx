import { InspectorSection } from '../../../components'
import { useEffect } from 'react'

import { useAssetStore, useWorkspaceIntelligenceStore, useWorkspaceStore } from '../../../stores'

export function InspectorPanel() {
  const inspectorOpen = useWorkspaceStore((state) => state.inspectorOpen)
  const toggleInspector = useWorkspaceStore((state) => state.toggleInspector)
  const selectedAssetId = useAssetStore((state) => state.selectedAssetId)
  const assets = useAssetStore((state) => state.assets)
  const selectedAsset = assets.find((asset) => asset.id === selectedAssetId)
  const graph = useWorkspaceIntelligenceStore((state) => state.graph)
  const selectedAssetLineage = useWorkspaceIntelligenceStore((state) => state.selectedAssetLineage)
  const loadAssetLineage = useWorkspaceIntelligenceStore((state) => state.loadAssetLineage)

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
