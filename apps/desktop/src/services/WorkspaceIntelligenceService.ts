import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  ContextBundle,
  KnowledgeGraph,
  KnowledgeNode,
  ProjectGraphPayload,
  WorkspaceContextPayload,
  WorkspaceDashboardPayload,
  WorkspaceRecommendationsPayload,
  WorkspaceRecentPayload,
} from '../api/types'

export interface WorkspaceIntelligenceService {
  context(projectId: string): Promise<WorkspaceContextPayload>
  recommendations(projectId: string): Promise<WorkspaceRecommendationsPayload>
  recent(projectId: string): Promise<WorkspaceRecentPayload>
  dashboard(projectId: string): Promise<WorkspaceDashboardPayload>
  graph(projectId: string): Promise<ProjectGraphPayload>
  graphContext(projectId: string): Promise<ContextBundle>
  graphLineage(assetId: string): Promise<KnowledgeGraph>
  graphNode(nodeId: string): Promise<KnowledgeNode | undefined>
  graphNeighbors(nodeId: string): Promise<KnowledgeNode[]>
  graphHistory(nodeId: string): Promise<Array<Record<string, unknown>>>
}

export const workspaceIntelligenceService: WorkspaceIntelligenceService = {
  async context(projectId) {
    return getAtlasProvider().getWorkspaceContext(projectId)
  },
  async recommendations(projectId) {
    return getAtlasProvider().getWorkspaceRecommendations(projectId)
  },
  async recent(projectId) {
    return getAtlasProvider().getWorkspaceRecent(projectId)
  },
  async dashboard(projectId) {
    return getAtlasProvider().getWorkspaceDashboard(projectId)
  },
  async graph(projectId) {
    return getAtlasProvider().getProjectGraph(projectId)
  },
  async graphContext(projectId) {
    return getAtlasProvider().getGraphContext(projectId)
  },
  async graphLineage(assetId) {
    return getAtlasProvider().getGraphLineage(assetId)
  },
  async graphNode(nodeId) {
    return getAtlasProvider().getGraphNode(nodeId)
  },
  async graphNeighbors(nodeId) {
    return getAtlasProvider().getGraphNeighbors(nodeId)
  },
  async graphHistory(nodeId) {
    return getAtlasProvider().getGraphHistory(nodeId)
  },
}
