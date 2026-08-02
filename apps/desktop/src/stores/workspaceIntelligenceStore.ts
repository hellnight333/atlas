import { create } from 'zustand'

import type {
  ApiError,
  ApiStatus,
  ContextBundle,
  KnowledgeGraph,
  KnowledgeNode,
  ProjectGraphPayload,
  WorkspaceContextPayload,
  WorkspaceDashboardPayload,
  WorkspaceRecommendationsPayload,
  WorkspaceRecentPayload,
} from '../api/types'
import { workspaceIntelligenceService } from '../services/WorkspaceIntelligenceService'
import { toApiError } from '../services/types'

type WorkspaceIntelligenceStore = {
  context: WorkspaceContextPayload | null
  recommendations: WorkspaceRecommendationsPayload | null
  recent: WorkspaceRecentPayload | null
  dashboard: WorkspaceDashboardPayload | null
  graph: ProjectGraphPayload | null
  graphContext: ContextBundle | null
  selectedNode: KnowledgeNode | null
  selectedNodeNeighbors: KnowledgeNode[]
  selectedNodeHistory: Array<Record<string, unknown>>
  selectedAssetLineage: KnowledgeGraph | null
  status: ApiStatus
  error: ApiError | null
  lastLoadedAt: number | null
  loadForProject: (projectId: string) => Promise<void>
  refreshForProject: (projectId: string) => Promise<void>
  loadNodeContext: (nodeId: string) => Promise<void>
  loadAssetLineage: (assetId: string) => Promise<void>
}

export const useWorkspaceIntelligenceStore = create<WorkspaceIntelligenceStore>((set, get) => ({
  context: null,
  recommendations: null,
  recent: null,
  dashboard: null,
  graph: null,
  graphContext: null,
  selectedNode: null,
  selectedNodeNeighbors: [],
  selectedNodeHistory: [],
  selectedAssetLineage: null,
  status: 'idle',
  error: null,
  lastLoadedAt: null,
  loadForProject: async (projectId) => {
    set((state) => ({ status: state.context ? 'refreshing' : 'loading', error: null }))
    try {
      const [context, recommendations, recent, dashboard, graph, graphContext] = await Promise.all([
        workspaceIntelligenceService.context(projectId),
        workspaceIntelligenceService.recommendations(projectId),
        workspaceIntelligenceService.recent(projectId),
        workspaceIntelligenceService.dashboard(projectId),
        workspaceIntelligenceService.graph(projectId),
        workspaceIntelligenceService.graphContext(projectId),
      ])
      set({
        context,
        recommendations,
        recent,
        dashboard,
        graph,
        graphContext,
        status: 'success',
        error: null,
        lastLoadedAt: Date.now(),
      })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  refreshForProject: async (projectId) => {
    await get().loadForProject(projectId)
  },
  loadNodeContext: async (nodeId) => {
    try {
      const [selectedNode, selectedNodeNeighbors, selectedNodeHistory] = await Promise.all([
        workspaceIntelligenceService.graphNode(nodeId),
        workspaceIntelligenceService.graphNeighbors(nodeId),
        workspaceIntelligenceService.graphHistory(nodeId),
      ])
      set({ selectedNode: selectedNode ?? null, selectedNodeNeighbors, selectedNodeHistory, error: null })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  loadAssetLineage: async (assetId) => {
    try {
      const selectedAssetLineage = await workspaceIntelligenceService.graphLineage(assetId)
      set({ selectedAssetLineage, error: null })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
}))
