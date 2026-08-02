import { createBrowserRouter } from 'react-router-dom'

import { ActivityCenterScreen } from '../features/activity/screens/ActivityCenterScreen'
import { ApprovalCenterScreen } from '../features/approval/screens/ApprovalCenterScreen'
import { ClusterStudioScreen } from '../features/cluster/screens/ClusterStudioScreen'
import { AssetWorkspaceScreen } from '../features/assets/screens/AssetWorkspaceScreen'
import { AutomationStudioScreen } from '../features/automation/screens/AutomationStudioScreen'
import { DesktopOverviewScreen } from '../features/projects/screens/DesktopOverviewScreen'
import { HomeWorkspaceScreen } from '../features/projects/screens/HomeWorkspaceScreen'
import { ProjectWorkspaceScreen } from '../features/projects/screens/ProjectWorkspaceScreen'
import { ChatStudioScreen } from '../features/chat/screens/ChatStudioScreen'
import { ImageStudioScreen } from '../features/image/screens/ImageStudioScreen'
import { ReviewStudioScreen } from '../features/review/screens/ReviewStudioScreen'
import { AgentStudioScreen } from '../features/studios/screens/AgentStudioScreen'
import { StudioWorkspaceScreen } from '../features/studios/screens/StudioWorkspaceScreen'
import { WorkflowStudioScreen } from '../features/studios/screens/WorkflowStudioScreen'
import { ResearchWorkspaceScreen } from '../features/workspace/screens/ResearchWorkspaceScreen'
import { DesktopShellLayout } from '../layouts/DesktopShellLayout'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <DesktopShellLayout />,
    children: [
      { index: true, element: <DesktopOverviewScreen /> },
      { path: 'workspace', element: <HomeWorkspaceScreen /> },
      { path: 'project/:id', element: <ProjectWorkspaceScreen /> },
      { path: 'project/:id/chat', element: <ChatStudioScreen /> },
      { path: 'asset/:id', element: <AssetWorkspaceScreen /> },
      { path: 'studio/:id', element: <StudioWorkspaceScreen /> },
      { path: 'workflow-studio', element: <WorkflowStudioScreen /> },
      { path: 'research', element: <ResearchWorkspaceScreen /> },
      { path: 'image-studio', element: <ImageStudioScreen /> },
      { path: 'review', element: <ReviewStudioScreen /> },
      { path: 'agent-studio', element: <AgentStudioScreen /> },
      { path: 'automation', element: <AutomationStudioScreen /> },
      { path: 'approvals', element: <ApprovalCenterScreen /> },
      { path: 'cluster', element: <ClusterStudioScreen /> },
      { path: 'mission-control', element: <HomeWorkspaceScreen /> },
      { path: 'activity-center', element: <ActivityCenterScreen /> },
    ],
  },
])
