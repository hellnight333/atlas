export type Capability = 'Research' | 'Media' | 'Build' | 'Publish'

export type StudioKind = 'Core' | 'Extended' | 'Marketplace' | 'Plugin'

export type ProjectStatus = 'active' | 'paused' | 'at-risk'

export type Freshness = 'authoritative_live' | 'authoritative_indexed' | 'stale_indexed'

export type Severity = 'info' | 'attention' | 'warning' | 'critical'

export type JobState =
  | 'accepted'
  | 'queued'
  | 'running'
  | 'blocked'
  | 'succeeded'
  | 'succeeded_with_warnings'
  | 'failed_recoverable'
  | 'failed_terminal'
  | 'canceled'

export type CommandMode = 'command' | 'search' | 'quick-action' | 'ai'

export type Project = {
  id: string
  name: string
  studio: string
  status: ProjectStatus
  progress: number
  description?: string
  workspaceId?: string | null
}

export type Studio = {
  id: string
  name: string
  capability: Capability
  kind: StudioKind
}

export type Asset = {
  id: string
  title: string
  type: 'Document' | 'Video' | 'Image' | 'Dataset' | 'Workflow' | 'Code' | 'Text'
  projectId: string
  freshness: Freshness
  version: number
  uri: string
  mimeType?: string | null
  fileSize?: number | null
  contentHash?: string | null
  createdAt?: string
  updatedAt?: string
  metadata?: Record<string, unknown>
  tags?: string[]
}

export type AgentTask = {
  id: string
  name: string
  projectId: string
  status: 'running' | 'blocked' | 'completed'
  confidence: number
}

export type Job = {
  id: string
  name: string
  projectId: string
  domain:
    | 'rendering'
    | 'research'
    | 'training'
    | 'publishing'
    | 'downloads'
    | 'uploads'
    | 'agent'
  state: JobState
  severity: Severity
  progress: number
  elapsed: string
}

export type NotificationItem = {
  id: string
  title: string
  detail: string
  severity: Severity
  pinned?: boolean
}

export type CommandItem = {
  id: string
  label: string
  kind:
    | 'navigation'
    | 'workspace-layout'
    | 'studio-action'
    | 'project-operation'
    | 'asset-operation'
    | 'search'
    | 'review'
    | 'publish'
    | 'system'
  scope: 'global' | 'project' | 'studio' | 'selection'
}
