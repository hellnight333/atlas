import type {
  AgentTask,
  Asset,
  CommandItem,
  Job,
  NotificationItem,
  Project,
  Studio,
} from '../types/domain'

export const mockProjects: Project[] = [
  { id: 'p1', name: 'Aurora Launch Film', studio: 'Video Studio', status: 'active', progress: 68, description: 'Launch campaign film', workspaceId: 'workspace-demo' },
  { id: 'p2', name: 'Atlas SaaS Narrative', studio: 'Research Studio', status: 'at-risk', progress: 43, description: 'Product positioning research', workspaceId: 'workspace-demo' },
  { id: 'p3', name: 'Mobile Product Teaser', studio: 'Image Studio', status: 'active', progress: 81, description: 'Mobile teaser visuals', workspaceId: 'workspace-demo' },
  { id: 'p4', name: 'Enterprise Playbook', studio: 'Publishing Studio', status: 'paused', progress: 25, description: 'Enterprise rollout docs', workspaceId: 'workspace-demo' },
]

export const mockStudios: Studio[] = [
  { id: 's1', name: 'Research Studio', capability: 'Research', kind: 'Core' },
  { id: 's2', name: 'Video Studio', capability: 'Media', kind: 'Core' },
  { id: 's3', name: 'Image Studio', capability: 'Media', kind: 'Extended' },
  { id: 's4', name: 'Product Studio', capability: 'Build', kind: 'Core' },
  { id: 's5', name: 'Publishing Studio', capability: 'Publish', kind: 'Core' },
  { id: 's6', name: 'Brand Pack Studio', capability: 'Media', kind: 'Marketplace' },
]

export const mockAssets: Asset[] = [
  { id: 'a1', title: 'Opening Sequence Storyboard', type: 'Image', projectId: 'p1', freshness: 'authoritative_live', version: 1, uri: 'file:///mock/opening-sequence.png', mimeType: 'image/png', fileSize: 128344, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), metadata: { original_filename: 'opening-sequence.png' }, tags: ['launch', 'storyboard'] },
  { id: 'a2', title: 'Research Synthesis v3', type: 'Document', projectId: 'p2', freshness: 'authoritative_indexed', version: 3, uri: 'file:///mock/research-synthesis.pdf', mimeType: 'application/pdf', fileSize: 84321, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), metadata: { original_filename: 'research-synthesis.pdf' }, tags: ['research'] },
  { id: 'a3', title: 'Mobile Motion Draft', type: 'Video', projectId: 'p3', freshness: 'authoritative_live', version: 2, uri: 'file:///mock/mobile-motion.mov', mimeType: 'video/quicktime', fileSize: 2450344, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), metadata: { original_filename: 'mobile-motion.mov' }, tags: ['motion'] },
  { id: 'a4', title: 'Market Interview Dataset', type: 'Dataset', projectId: 'p2', freshness: 'stale_indexed', version: 1, uri: 'file:///mock/interview-dataset.csv', mimeType: 'text/csv', fileSize: 48344, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), metadata: { original_filename: 'interview-dataset.csv' }, tags: ['dataset'] },
  { id: 'a5', title: 'Enterprise Readiness Checklist', type: 'Workflow', projectId: 'p4', freshness: 'authoritative_indexed', version: 1, uri: 'file:///mock/enterprise-readiness.md', mimeType: 'text/markdown', fileSize: 1244, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), metadata: { original_filename: 'enterprise-readiness.md' }, tags: ['checklist'] },
]

export const mockAgentTasks: AgentTask[] = [
  { id: 'g1', name: 'Narrative Variant Agent', projectId: 'p1', status: 'running', confidence: 0.82 },
  { id: 'g2', name: 'Source Integrity Agent', projectId: 'p2', status: 'blocked', confidence: 0.63 },
  { id: 'g3', name: 'Metadata Cleanup Agent', projectId: 'p3', status: 'completed', confidence: 0.91 },
]

export const mockJobs: Job[] = [
  { id: 'j1', name: 'Thumbnail Rendering Batch', projectId: 'p1', domain: 'rendering', state: 'running', severity: 'attention', progress: 64, elapsed: '07:12' },
  { id: 'j2', name: 'Research Clustering', projectId: 'p2', domain: 'research', state: 'blocked', severity: 'warning', progress: 38, elapsed: '12:01' },
  { id: 'j3', name: 'Publishing Dry Run', projectId: 'p4', domain: 'publishing', state: 'failed_recoverable', severity: 'warning', progress: 82, elapsed: '03:44' },
  { id: 'j4', name: 'Voice Sync Training', projectId: 'p1', domain: 'training', state: 'running', severity: 'info', progress: 24, elapsed: '15:33' },
]

export const mockNotifications: NotificationItem[] = [
  { id: 'n1', title: 'Blocked Dependency', detail: 'Research Clustering needs source approval in Atlas SaaS Narrative.', severity: 'warning', pinned: true },
  { id: 'n2', title: 'Rendering Completed', detail: 'Sequence preview package is ready for review.', severity: 'info' },
  { id: 'n3', title: 'Critical Sync Degradation', detail: 'Cloud sync is delayed beyond policy threshold.', severity: 'critical', pinned: true },
]

export const mockCommands: CommandItem[] = [
  { id: 'c1', label: 'Open Mission Control', kind: 'navigation', scope: 'global' },
  { id: 'c2', label: 'Switch to Research Studio', kind: 'studio-action', scope: 'project' },
  { id: 'c3', label: 'Open Activity Center', kind: 'navigation', scope: 'global' },
  { id: 'c4', label: 'Run Publish Checklist', kind: 'publish', scope: 'project' },
  { id: 'c5', label: 'Compare Latest Asset Versions', kind: 'review', scope: 'selection' },
  { id: 'c6', label: 'Pin Current Workspace Layout', kind: 'workspace-layout', scope: 'studio' },
  { id: 'c7', label: 'Search Project Assets', kind: 'search', scope: 'project' },
  { id: 'c8', label: 'Open Enterprise Policy Visibility', kind: 'system', scope: 'global' },
]

export const mockRecentCommandIds = ['c2', 'c7', 'c3', 'c5']
export const mockPinnedCommandIds = ['c1', 'c4', 'c6']
