export type ScreenId =
  | 'desktop-overview'
  | 'home-workspace'
  | 'project-workspace'
  | 'studio-workspace'
  | 'asset-workspace'
  | 'mission-control'
  | 'command-palette'
  | 'activity-center'

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

export type Severity = 'info' | 'attention' | 'warning' | 'critical'

export type CommandMode = 'command' | 'search' | 'quick-action' | 'ai'

export type Project = {
  id: string
  name: string
  studio: string
  status: 'active' | 'paused' | 'at-risk'
  progress: number
}

export type Studio = {
  id: string
  name: string
  capability: 'Research' | 'Media' | 'Build' | 'Publish'
  kind: 'Core' | 'Extended' | 'Marketplace' | 'Plugin'
}

export type Asset = {
  id: string
  title: string
  type: 'Document' | 'Video' | 'Image' | 'Dataset' | 'Workflow'
  projectId: string
  freshness: 'authoritative_live' | 'authoritative_indexed' | 'stale_indexed'
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