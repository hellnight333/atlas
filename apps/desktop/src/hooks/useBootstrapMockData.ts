import { useEffect } from 'react'

import {
  useActivityStore,
  useAgentStore,
  useAssetStore,
  useChatStore,
  useCommandPaletteStore,
  useImageStore,
  useNotificationStore,
  useProjectStore,
  useReviewStore,
  useWorkspaceIntelligenceStore,
  useWorkflowStore,
  useWorkspaceStore,
} from '../stores'

export function useBootstrapMockData() {
  const loadProjects = useProjectStore((state) => state.loadProjects)
  const loadAssets = useAssetStore((state) => state.loadAssets)
  const loadActivity = useActivityStore((state) => state.loadActivity)
  const loadNotifications = useNotificationStore((state) => state.loadNotifications)
  const loadStudios = useWorkspaceStore((state) => state.loadStudios)
  const loadCommands = useCommandPaletteStore((state) => state.loadCommands)
  const loadWorkflows = useWorkflowStore((state) => state.loadWorkflows)
  const loadConversations = useChatStore((state) => state.loadConversations)
  const loadReviews = useReviewStore((state) => state.loadSessions)
  const loadImages = useImageStore((state) => state.loadImages)
  const loadWorkspaceIntelligence = useWorkspaceIntelligenceStore((state) => state.loadForProject)
  const loadAgents = useAgentStore((state) => state.loadAgents)

  useEffect(() => {
    void Promise.all([
      loadProjects(),
      loadAssets(),
      loadActivity(),
      loadNotifications(),
      loadStudios(),
      loadCommands(),
      loadWorkflows(),
      loadConversations('p1'),
      loadReviews('p1'),
      loadImages('p1'),
      loadAgents('p1'),
      loadWorkspaceIntelligence('p1'),
    ])
  }, [loadActivity, loadAgents, loadAssets, loadCommands, loadConversations, loadImages, loadNotifications, loadProjects, loadReviews, loadStudios, loadWorkspaceIntelligence, loadWorkflows])
}
