import type {
  AgentTask,
  Asset,
  CommandItem,
  Job,
  NotificationItem,
  Project,
  Studio,
} from '../types/domain'

export type ProviderMode = 'mock' | 'kernel-local' | 'kernel-remote'

export type ApiErrorCode =
  | 'UNKNOWN'
  | 'NETWORK_UNAVAILABLE'
  | 'OFFLINE'
  | 'PROVIDER_UNAVAILABLE'
  | 'NOT_IMPLEMENTED'
  | 'TIMEOUT'
  | 'BAD_RESPONSE'

export type ApiError = {
  code: ApiErrorCode
  message: string
  retryable: boolean
  cause?: unknown
}

export type ApiStatus = 'idle' | 'loading' | 'success' | 'error' | 'empty' | 'refreshing'

export type ResourceState<T> = {
  data: T
  status: ApiStatus
  error: ApiError | null
  lastLoadedAt: number | null
}

export type SearchResult = {
  id: string
  title: string
  type: 'project' | 'asset' | 'studio' | 'command' | 'activity'
  scope: string
}

export type ResearchSession = {
  id: string
  project_id: string
  title: string
  question: string
  status: string
  conversation_id?: string | null
  collection_asset_id?: string | null
  report_asset_id?: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type ResearchGraphNode = {
  id: string
  type: string
  label: string
  asset_id?: string
}

export type ResearchGraphEdge = {
  id: string
  type: string
  from: string
  to: string
}

export type ResearchGraph = {
  project_id: string
  nodes: ResearchGraphNode[]
  edges: ResearchGraphEdge[]
  updated_at: string
}

export type KnowledgeNode = {
  id: string
  node_type: string
  label: string
  project_id?: string | null
  workspace_id?: string | null
  source_id?: string | null
  metadata: Record<string, unknown>
  archived: boolean
  created_at: string
}

export type KnowledgeEdge = {
  id: string
  relationship: string
  from_node: string
  to_node: string
  metadata: Record<string, unknown>
  created_at: string
}

export type KnowledgeGraph = {
  nodes: KnowledgeNode[]
  edges: KnowledgeEdge[]
}

export type GraphSnapshot = {
  id: string
  scope_type: string
  scope_id: string
  node_ids: string[]
  edge_ids: string[]
  created_at: string
}

export type ContextBundle = {
  project: Record<string, unknown>
  recent_chats: Array<Record<string, unknown>>
  related_assets: Array<Record<string, unknown>>
  research_findings: Array<Record<string, unknown>>
  reviews: Array<Record<string, unknown>>
  agent_history: Array<Record<string, unknown>>
  workflow_history: Array<Record<string, unknown>>
  execution_history: Array<Record<string, unknown>>
  referenced_images: Array<Record<string, unknown>>
  referenced_reports: Array<Record<string, unknown>>
  graph: KnowledgeGraph
}

export type ProjectGraphPayload = {
  graph: KnowledgeGraph
  snapshot: GraphSnapshot
}

export type ReviewItem = {
  id: string
  review_id: string
  asset_id: string
  decision: string
  comment?: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type ReviewComment = {
  id: string
  review_id: string
  content: string
  metadata: Record<string, unknown>
  created_at: string
}

export type ApprovalScope =
  | 'external_api'
  | 'filesystem_write'
  | 'network'
  | 'provider_cost'
  | 'project_publish'
  | 'delete'
  | 'plugin_action'
  | 'enterprise'

export type ApprovalState = 'pending' | 'approved' | 'rejected' | 'cancelled' | 'expired'

export type ApprovalDecisionKind = 'approve' | 'reject' | 'request_changes'

export type ApprovalDecisionRecord = {
  id: string
  decision: ApprovalDecisionKind
  actor: string
  comment?: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export type ApprovalRequest = {
  id: string
  title: string
  state: ApprovalState
  action: string
  scopes: ApprovalScope[]
  estimated_cost: number
  reason: string
  policy_id?: string | null
  policy_name?: string | null
  required_approvers: string[]
  approvals_required: number
  decisions: ApprovalDecisionRecord[]
  viewed_by: string[]
  priority: number
  project_id?: string | null
  workspace_id?: string | null
  agent_id?: string | null
  execution_id?: string | null
  schedule_id?: string | null
  entry_id?: string | null
  run_id?: string | null
  job_id?: string | null
  asset_id?: string | null
  payload: Record<string, unknown>
  metadata: Record<string, unknown>
  requested_by: string
  created_at: string
  updated_at: string
  expires_at?: string | null
  decided_at?: string | null
}

export type ApprovalHistoryEvent = {
  id: string
  approval_id: string
  event_type: string
  actor: string
  comment?: string | null
  from_state?: ApprovalState | null
  to_state?: ApprovalState | null
  metadata: Record<string, unknown>
  created_at: string
}

export type ApprovalPolicyMode = 'always' | 'never' | 'scoped'

export type ApprovalPolicyCondition = {
  field: string
  operator: string
  value: unknown
}

export type ApprovalPolicy = {
  id: string
  name: string
  description: string
  mode: ApprovalPolicyMode
  scopes: ApprovalScope[]
  cost_threshold?: number | null
  conditions: ApprovalPolicyCondition[]
  required_approvers: string[]
  approvals_required: number
  expires_after_seconds?: number | null
  project_id?: string | null
  workspace_id?: string | null
  priority: number
  enabled: boolean
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type ApprovalCreatePayload = {
  title: string
  action?: string
  scopes?: ApprovalScope[]
  estimatedCost?: number
  projectId?: string
  workspaceId?: string
  agentId?: string
  executionId?: string
  scheduleId?: string
  entryId?: string
  priority?: number
  payload?: Record<string, unknown>
  metadata?: Record<string, unknown>
  requestedBy?: string
}

export type ApprovalDecisionPayload = {
  actor: string
  comment?: string
}

export type AutomationTriggerType =
  | 'manual'
  | 'timer'
  | 'cron'
  | 'asset_imported'
  | 'asset_updated'
  | 'asset_published'
  | 'review_approved'
  | 'review_rejected'
  | 'workflow_completed'
  | 'workflow_failed'
  | 'agent_completed'
  | 'project_created'
  | 'project_opened'
  | 'research_completed'
  | 'image_generated'
  | 'video_generated'

export type AutomationTrigger = {
  type: AutomationTriggerType
  timer_seconds?: number | null
  cron_expression?: string | null
  metadata: Record<string, unknown>
}

export type AutomationCondition = {
  type: string
  operator: string
  value: unknown
  metadata: Record<string, unknown>
}

export type AutomationAction = {
  type: string
  payload: Record<string, unknown>
  metadata: Record<string, unknown>
}

export type AutomationRule = {
  id: string
  project_id?: string | null
  workspace_id?: string | null
  name: string
  description: string
  trigger: AutomationTrigger
  conditions: AutomationCondition[]
  actions: AutomationAction[]
  schedule?: Record<string, unknown> | null
  priority: number
  enabled: boolean
  dry_run: boolean
  created_at: string
  updated_at: string
  disabled_at?: string | null
}

export type AutomationRunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

export type AutomationRun = {
  id: string
  rule_id: string
  triggered_by: string
  status: AutomationRunStatus
  start_time: string
  end_time?: string | null
  duration_ms?: number | null
  trigger_data: Record<string, unknown>
  outputs: Record<string, unknown>
  error?: string | null
  retries: number
  created_at: string
}

export type AutomationLog = {
  id: string
  run_id?: string | null
  rule_id: string
  level: 'debug' | 'info' | 'warning' | 'error'
  message: string
  actor: string
  context: Record<string, unknown>
  created_at: string
}

export type AutomationState = {
  rule_id: string
  enabled: boolean
  last_run_id?: string | null
  last_status?: AutomationRunStatus | null
  last_run_at?: string | null
  next_run_at?: string | null
  total_runs: number
  failure_count: number
}

export type AutomationConflict = {
  trigger: string
  priority: number
  rule_ids: string[]
}

export type AutomationRuleRequest = {
  name: string
  description?: string
  trigger: AutomationTrigger
  conditions?: AutomationCondition[]
  actions?: AutomationAction[]
  projectId?: string
  workspaceId?: string
  schedule?: Record<string, unknown> | null
  priority?: number
  dryRun?: boolean
  actor?: string
}

export type AutomationRuleUpdateRequest = Partial<
  Pick<AutomationRuleRequest, 'name' | 'description' | 'trigger' | 'conditions' | 'actions' | 'schedule' | 'priority' | 'dryRun' | 'actor'>
>

export type AutomationRunRequest = {
  triggerData?: Record<string, unknown>
  agentId?: string
  actor?: string
}

export type ReviewHistoryEvent = {
  id: string
  review_id: string
  event_type: string
  actor: string
  comment?: string | null
  from_status?: string | null
  to_status?: string | null
  asset_id?: string | null
  published_asset_id?: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export type ReviewSession = {
  id: string
  project_id: string
  title: string
  status: string
  asset_id?: string | null
  published_asset_id?: string | null
  workflow_id?: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  items?: ReviewItem[]
  comments?: ReviewComment[]
}

export type ReviewSessionRequest = {
  projectId: string
  title: string
  assetId?: string
  workflowId?: string
  metadata?: Record<string, unknown>
}

export type ReviewDecisionRequest = {
  assetId: string
  comment?: string
  metadata?: Record<string, unknown>
}

export type ReviewCommentRequest = {
  content: string
  metadata?: Record<string, unknown>
}

export type ReviewPublishRequest = {
  assetId: string
  metadata?: Record<string, unknown>
}

export type ImageAsset = {
  id: string
  project_id: string
  run_id?: string | null
  job_id?: string | null
  workflow_id?: string | null
  parent_asset_id?: string | null
  version: number
  uri: string
  thumbnail_uri?: string | null
  content_hash?: string | null
  prompt: string
  negative_prompt: string
  styles: string[]
  template?: string | null
  variables: Record<string, unknown>
  prompt_history: string[]
  prompt_version: number
  seed?: number | null
  steps?: number | null
  cfg?: number | null
  resolution?: string | null
  sampler?: string | null
  provider?: string | null
  workflow?: string | null
  model?: string | null
  execution_time_ms?: number | null
  metadata: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export type ImageGenerateRequest = {
  projectId: string
  prompt: string
  negativePrompt?: string
  styles?: string[]
  template?: string
  variables?: Record<string, unknown>
  seed?: number
  steps?: number
  cfg?: number
  resolution?: string
  sampler?: string
  provider?: string
  workflow?: string
  model?: string
  metadata?: Record<string, unknown>
}

export type ImageVariantRequest = {
  prompt?: string
  negativePrompt?: string
  styles?: string[]
  template?: string
  variables?: Record<string, unknown>
  seed?: number
  steps?: number
  cfg?: number
  resolution?: string
  sampler?: string
  provider?: string
  workflow?: string
  model?: string
  metadata?: Record<string, unknown>
}

export type ImageGenerationResult = {
  run: Record<string, unknown>
  job: Record<string, unknown>
  image: ImageAsset
}

export type WorkspaceRecommendation = {
  type: string
  title: string
  reason: string
  action: string
  reference_id?: string
}

export type WorkspaceContextPayload = {
  workspace_context: {
    project: Record<string, unknown>
    project_summary: Record<string, unknown>
    recent_activity: Array<Record<string, unknown>>
    recent_assets: Array<Record<string, unknown>>
    pinned_assets: Array<Record<string, unknown>>
    open_tasks: Array<Record<string, unknown>>
    suggested_tasks: WorkspaceRecommendation[]
    recent_conversations: Array<Record<string, unknown>>
    recent_research: Array<Record<string, unknown>>
    recent_reviews: Array<Record<string, unknown>>
    recent_images: Array<Record<string, unknown>>
    knowledge_highlights: Array<Record<string, unknown>>
    recommendations: WorkspaceRecommendation[]
  }
}

export type WorkspaceRecommendationsPayload = {
  project_id: string
  recommendations: WorkspaceRecommendation[]
}

export type WorkspaceRecentPayload = {
  project_id: string
  recent_activity: Array<Record<string, unknown>>
  recent_assets: Array<Record<string, unknown>>
  recent_conversations: Array<Record<string, unknown>>
  recent_research: Array<Record<string, unknown>>
  recent_reviews: Array<Record<string, unknown>>
  recent_images: Array<Record<string, unknown>>
  recent_workflows: Array<Record<string, unknown>>
  recent_runs: Array<Record<string, unknown>>
}

export type WorkspaceDashboardPayload = {
  project_summary: Record<string, unknown>
  project_health: Record<string, unknown>
  recent_timeline: Array<Record<string, unknown>>
  recent_workflows: Array<Record<string, unknown>>
  research_progress: Record<string, unknown>
  review_queue: Array<Record<string, unknown>>
  image_queue: Array<Record<string, unknown>>
  knowledge_growth: Record<string, unknown>
}

export type AgentStatus =
  | 'idle'
  | 'planning'
  | 'executing'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type AgentPermission =
  | 'read_assets'
  | 'write_assets'
  | 'execute_workflow'
  | 'review_assets'
  | 'publish_assets'
  | 'delete_assets'
  | 'modify_project'
  | 'manage_agents'

export type AgentRole =
  | 'research'
  | 'planner'
  | 'writer'
  | 'reviewer'
  | 'image'
  | 'video'
  | 'developer'
  | 'operator'

export type Agent = {
  id: string
  name: string
  description: string
  role: string
  workspace_id?: string | null
  project_id?: string | null
  capabilities: string[]
  status: AgentStatus
  memory_id: string
  permission_set: AgentPermission[]
  created_at: string
  updated_at: string
}

export type AgentCreateRequest = {
  name: string
  description?: string
  role: string
  workspaceId?: string
  projectId?: string
  capabilities?: string[]
  status?: AgentStatus
  memoryId?: string
  permissionSet?: AgentPermission[]
}

export type AgentUpdateRequest = {
  name?: string
  description?: string
  role?: string
  workspaceId?: string
  projectId?: string
  capabilities?: string[]
  status?: AgentStatus
  memoryId?: string
  permissionSet?: AgentPermission[]
}

export type AgentMemoryReference = {
  id: string
  memory_id: string
  agent_id: string
  kind: string
  asset_id: string
  created_at: string
}

export type AgentMemoryAttachRequest = {
  kind: string
  assetId: string
}

export type PlannerStepEstimate = {
  tokens: number
  gpu_seconds: number
  provider_class: string
  latency_seconds: number
  overall_cost_usd: number
}

export type PlannerStep = {
  id: string
  description: string
  capability: string
  action: string
  payload: Record<string, unknown>
  expected_output: string
  dependencies: string[]
  estimated_cost_usd: number
  estimated_time_seconds: number
  review_required: boolean
  estimate: PlannerStepEstimate
}

export type PlannerExecutionPlan = {
  plan_id: string
  goal: string
  confidence: number
  estimated_duration_seconds: number
  estimated_cost_usd: number
  steps: PlannerStep[]
  dependencies: Array<{ from: string; to: string }>
  capabilities_required: string[]
  assets_required: string[]
  expected_outputs: string[]
  review_required: boolean
  context_snapshot: Record<string, unknown>
  created_at: string
}

export type AgentPlanRequest = {
  goal: string
}

export type SchedulerPriority = 'immediate' | 'high' | 'normal' | 'low' | 'background'

export type QueueEntryStatus =
  | 'queued'
  | 'ready'
  | 'blocked'
  | 'waiting_approval'
  | 'preparing'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'timed_out'

export type SchedulerCreateRequest = {
  agentId: string
  goal: string
  priority?: SchedulerPriority
  availableExecutors?: string[]
  executionPolicy?: Record<string, unknown>
}

export type ScheduleQueueEntry = {
  id: string
  plan_step: PlannerStep
  status: QueueEntryStatus
  priority: SchedulerPriority
  dependencies: string[]
  executor_hint?: string | null
  capability: string
  retry_count: number
  scheduled_time: string
  started_time?: string | null
  completed_time?: string | null
}

export type ResumeToken = {
  token: string
  entry_id: string
  created_at: string
  metadata: Record<string, unknown>
}

export type ExecutionSchedule = {
  schedule_id: string
  plan_id: string
  agent_id: string
  created_at: string
  priority: SchedulerPriority
  estimated_finish_time?: string | null
  queue_entries: ScheduleQueueEntry[]
  blocked_entries: string[]
  parallel_groups: string[][]
  resume_tokens: ResumeToken[]
  queue_metadata: Record<string, unknown>
}

export type QueueUpdateResult = {
  schedule_id: string
  updated_entries: string[]
  status: string
}

export type RuntimeExecutionStatus =
  | 'pending'
  | 'queued'
  | 'waiting_approval'
  | 'approval_rejected'
  | 'preparing'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'timed_out'

export type RuntimeRetryPolicy = {
  max_attempts: number
  retry_delay: number
  backoff: number
}

export type RuntimeTimelineEntry = {
  status: string
  timestamp: string
  attempt?: number
  reason?: string
}

export type RuntimeExecutionRecord = {
  execution_id: string
  schedule_id: string
  entry_id: string
  agent_id: string
  plan_id: string
  action: string
  payload: Record<string, unknown>
  status: RuntimeExecutionStatus
  attempts: number
  retry_policy: RuntimeRetryPolicy
  created_at: string
  updated_at: string
  started_at?: string | null
  heartbeat_at?: string | null
  deadline_at?: string | null
  completed_at?: string | null
  timeout_reason?: string | null
  error?: string | null
  provider_name?: string | null
  run_id?: string | null
  job_id?: string | null
  asset_id?: string | null
  output: Record<string, unknown>
  cancellation_requested: boolean
  timeline: RuntimeTimelineEntry[]
}

export type AgentMessageType =
  | 'TaskAssignment'
  | 'ProgressUpdate'
  | 'Question'
  | 'Answer'
  | 'ApprovalRequest'
  | 'ApprovalGranted'
  | 'ApprovalRejected'
  | 'AssetReference'
  | 'Completion'
  | 'Failure'

export type AgentMessage = {
  id: string
  sender: string
  receiver: string
  timestamp: string
  type: AgentMessageType
  payload: Record<string, unknown>
  correlation_id?: string | null
  reply_to?: string | null
}

export type AgentAssignmentStatus =
  | 'pending'
  | 'queued'
  | 'waiting'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type AgentAssignment = {
  id: string
  team_id: string
  agent_id: string
  role: AgentRole
  title: string
  status: AgentAssignmentStatus
  capabilities: string[]
  allowed_actions: string[]
  permissions: AgentPermission[]
  resource_limits: Record<string, number>
  action: string
  payload: Record<string, unknown>
  dependencies: string[]
  mailbox_id: string
  schedule_id?: string | null
  runtime_execution_id?: string | null
  result_asset_id?: string | null
  error?: string | null
  created_at: string
  updated_at: string
}

export type AgentTeamStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type AgentTeam = {
  id: string
  name: string
  project_id?: string | null
  workspace_id?: string | null
  status: AgentTeamStatus
  assignments: AgentAssignment[]
  conversation_ids: string[]
  created_at: string
  updated_at: string
}

export type AgentAssignmentRequest = {
  agentId: string
  role: AgentRole
  title: string
  action: string
  payload?: Record<string, unknown>
  dependencies?: string[]
}

export type AgentTeamCreateRequest = {
  name: string
  projectId?: string
  workspaceId?: string
  assignments: AgentAssignmentRequest[]
}

export type AgentTeamStatusPayload = {
  team_id: string
  status: AgentTeamStatus
  waiting: string[]
  running: string[]
  completed: string[]
  failed: string[]
}

export type ResearchSessionRequest = {
  projectId: string
  title: string
  question: string
  conversationId?: string
  metadata?: Record<string, unknown>
}

export type ResearchSearchRequest = {
  sessionId: string
  query: string
  provider?: string
}

export type ResearchSummarizeRequest = {
  sessionId: string
  sourceAssetIds: string[]
  prompt?: string
}

export type ResearchReportRequest = {
  sessionId: string
  format?: 'markdown' | 'text' | 'pdf'
  prompt?: string
}

export type ChatConversation = {
  id: string
  project_id: string
  title: string
  pinned: boolean
  prompt_version: number
  response_version: number
  provider_name?: string | null
  execution_time_ms?: number | null
  tokens?: number | null
  workflow_id?: string | null
  parent_conversation_id?: string | null
  prompt_asset_id?: string | null
  response_asset_id?: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  messages?: ChatMessage[]
}

export type ChatMessage = {
  id: string
  conversation_id: string
  version: number
  role: 'system' | 'user' | 'assistant'
  content: string
  asset_id?: string | null
  prompt_asset_id?: string | null
  response_asset_id?: string | null
  provider_name?: string | null
  execution_time_ms?: number | null
  tokens?: number | null
  metadata: Record<string, unknown>
  created_at: string
}

export type ChatConversationRequest = {
  projectId: string
  title: string
  pinned?: boolean
  parentConversationId?: string
  workflowId?: string
  metadata?: Record<string, unknown>
}

export type ChatConversationUpdateRequest = {
  title?: string
  pinned?: boolean
  providerName?: string | null
  executionTimeMs?: number | null
  tokens?: number | null
  workflowId?: string | null
  parentConversationId?: string | null
  promptAssetId?: string | null
  responseAssetId?: string | null
  metadata?: Record<string, unknown>
}

export type ChatMessageRequest = {
  conversationId: string
  role: 'system' | 'user' | 'assistant'
  content: string
  assetId?: string | null
  promptAssetId?: string | null
  responseAssetId?: string | null
  providerName?: string | null
  executionTimeMs?: number | null
  tokens?: number | null
  metadata?: Record<string, unknown>
}

export type WorkflowExecutionRequest = {
  workflowId: string
  projectId?: string
  studioId?: string
}

export type WorkflowExecutionResult = {
  accepted: boolean
  runId?: string
}

export type AssetImportRequest = {
  file: File
  projectId: string
  workflowId?: string
  runId?: string
  jobId?: string
  assetType?: string
  tags?: string[]
}

export type Capability = {
  id: string
  name: string
  studioIds: string[]
}

export type WorkflowNodePayload = {
  id: string
  action: string
  payload: Record<string, unknown>
  depends_on: string[]
  input_asset_ids: string[]
  output_labels: string[]
  capability_req: {
    capability_id: string
    requirements: Record<string, unknown>
  }
  max_retries: number
  retry_delay_seconds: number
  failure_strategy: string
  condition_expression: string | null
}

export type WorkflowDefinitionPayload = {
  id: string
  name: string
  project_id: string
  workflow_id?: string | null
  nodes: WorkflowNodePayload[]
}

export type WorkflowExecutionPayload = {
  id: string
  workflow_definition_id: string
  run_id: string
  project_id: string
  workflow_id?: string | null
  state: string
  nodes: Record<string, { node_id: string; state: string; attempts: number; job_id?: string | null; produced_asset_ids: string[]; error?: string | null }>
}

export interface AtlasProvider {
  readonly mode: ProviderMode
  getProjects(): Promise<Project[]>
  getProject(id: string): Promise<Project | undefined>
  getAssets(): Promise<Asset[]>
  getProjectAssets(projectId: string): Promise<Asset[]>
  getAsset(id: string): Promise<Asset | undefined>
  importAsset(request: AssetImportRequest): Promise<Asset>
  deleteAsset(id: string): Promise<void>
  getRuns(): Promise<Job[]>
  getActivities(): Promise<Job[]>
  getAgentTasks(): Promise<AgentTask[]>
  getNotifications(): Promise<NotificationItem[]>
  getCapabilities(): Promise<Capability[]>
  getStudios(): Promise<Studio[]>
  getCommands(): Promise<CommandItem[]>
  getWorkflows(): Promise<WorkflowDefinitionPayload[]>
  getWorkflow(id: string): Promise<WorkflowDefinitionPayload | undefined>
  createWorkflow(definition: WorkflowDefinitionPayload): Promise<WorkflowDefinitionPayload>
  executeWorkflowDefinition(id: string): Promise<WorkflowExecutionPayload>
  getExecution(id: string): Promise<WorkflowExecutionPayload | undefined>
  getExecutionTimeline(id: string): Promise<Array<Record<string, unknown>>>
  search(query: string): Promise<SearchResult[]>
  executeWorkflow(request: WorkflowExecutionRequest): Promise<WorkflowExecutionResult>
  createChatConversation(request: ChatConversationRequest): Promise<ChatConversation>
  listChatConversations(projectId?: string): Promise<ChatConversation[]>
  getChatConversation(id: string): Promise<ChatConversation | undefined>
  sendChatMessage(request: ChatMessageRequest): Promise<ChatMessage>
  updateChatConversation(id: string, request: ChatConversationUpdateRequest): Promise<ChatConversation>
  deleteChatConversation(id: string): Promise<void>
  createResearchSession(request: ResearchSessionRequest): Promise<ResearchSession>
  listResearchSessions(projectId?: string): Promise<ResearchSession[]>
  getResearchSession(id: string): Promise<ResearchSession | undefined>
  searchResearch(request: ResearchSearchRequest): Promise<{ session_id: string; provider: string; sources: Array<Record<string, unknown>> }>
  summarizeResearch(request: ResearchSummarizeRequest): Promise<{ run_id: string; job_id: string; provider: string; asset: Record<string, unknown> }>
  generateResearchReport(request: ResearchReportRequest): Promise<Record<string, unknown>>
  getResearchGraph(projectId: string): Promise<ResearchGraph>
  createReviewSession(request: ReviewSessionRequest): Promise<ReviewSession>
  listReviewSessions(projectId?: string): Promise<ReviewSession[]>
  approveReview(id: string, request: ReviewDecisionRequest): Promise<ReviewSession>
  rejectReview(id: string, request: ReviewDecisionRequest): Promise<ReviewSession>
  commentReview(id: string, request: ReviewCommentRequest): Promise<ReviewComment>
  publishReview(id: string, request: ReviewPublishRequest): Promise<Record<string, unknown>>
  getReviewHistory(id: string): Promise<ReviewHistoryEvent[]>
  generateImage(request: ImageGenerateRequest): Promise<ImageGenerationResult>
  listImages(projectId?: string): Promise<ImageAsset[]>
  getImage(id: string): Promise<ImageAsset | undefined>
  createImageVariant(id: string, request: ImageVariantRequest): Promise<ImageGenerationResult>
  regenerateImage(id: string, request: ImageVariantRequest): Promise<ImageGenerationResult>
  getImageVersions(id: string): Promise<ImageAsset[]>
  getWorkspaceContext(projectId: string): Promise<WorkspaceContextPayload>
  getWorkspaceRecommendations(projectId: string): Promise<WorkspaceRecommendationsPayload>
  getWorkspaceRecent(projectId: string): Promise<WorkspaceRecentPayload>
  getWorkspaceDashboard(projectId: string): Promise<WorkspaceDashboardPayload>
  listAgents(projectId?: string): Promise<Agent[]>
  getAgent(id: string): Promise<Agent | undefined>
  createAgent(request: AgentCreateRequest): Promise<Agent>
  updateAgent(id: string, request: AgentUpdateRequest): Promise<Agent>
  deleteAgent(id: string): Promise<void>
  listAgentMemory(id: string): Promise<AgentMemoryReference[]>
  attachAgentMemory(id: string, request: AgentMemoryAttachRequest): Promise<AgentMemoryReference>
  getAgentPermissions(id: string): Promise<AgentPermission[]>
  generateAgentPlan(id: string, request: AgentPlanRequest): Promise<PlannerExecutionPlan>
  createSchedule(request: SchedulerCreateRequest): Promise<ExecutionSchedule>
  getSchedule(id: string): Promise<ExecutionSchedule>
  getScheduleQueue(id: string): Promise<ScheduleQueueEntry[]>
  pauseSchedule(id: string): Promise<QueueUpdateResult>
  resumeSchedule(id: string): Promise<QueueUpdateResult>
  cancelSchedule(id: string): Promise<QueueUpdateResult>
  startRuntimeSchedule(id: string): Promise<RuntimeExecutionRecord[]>
  listRuntime(): Promise<RuntimeExecutionRecord[]>
  listRuntimeRunning(): Promise<RuntimeExecutionRecord[]>
  listRuntimeHistory(): Promise<RuntimeExecutionRecord[]>
  getRuntimeExecution(id: string): Promise<RuntimeExecutionRecord | undefined>
  cancelRuntimeExecution(id: string): Promise<RuntimeExecutionRecord>
  retryRuntimeExecution(id: string): Promise<RuntimeExecutionRecord>
  createAgentTeam(request: AgentTeamCreateRequest): Promise<AgentTeam>
  getAgentTeam(id: string): Promise<AgentTeam | undefined>
  getAgentTeamMessages(id: string): Promise<AgentMessage[]>
  cancelAgentTeam(id: string): Promise<AgentTeam>
  getAgentTeamStatus(id: string): Promise<AgentTeamStatusPayload>
  getProjectGraph(id: string): Promise<ProjectGraphPayload>
  getGraphNode(id: string): Promise<KnowledgeNode | undefined>
  getGraphNeighbors(id: string): Promise<KnowledgeNode[]>
  getGraphPath(start: string, end: string): Promise<{ path: string[] }>
  getGraphContext(projectId: string): Promise<ContextBundle>
  getGraphLineage(assetId: string): Promise<KnowledgeGraph>
  getGraphHistory(nodeId: string): Promise<Array<Record<string, unknown>>>
  listAutomationRules(projectId?: string): Promise<AutomationRule[]>
  getAutomationRule(id: string): Promise<AutomationRule | undefined>
  createAutomationRule(request: AutomationRuleRequest): Promise<AutomationRule>
  updateAutomationRule(id: string, request: AutomationRuleUpdateRequest): Promise<AutomationRule>
  deleteAutomationRule(id: string): Promise<void>
  enableAutomationRule(id: string): Promise<AutomationRule>
  disableAutomationRule(id: string): Promise<AutomationRule>
  runAutomationRule(id: string, request?: AutomationRunRequest): Promise<AutomationRun>
  dryRunAutomationRule(id: string, request?: AutomationRunRequest): Promise<AutomationRun>
  getAutomationHistory(id: string): Promise<AutomationRun[]>
  getAutomationState(id: string): Promise<AutomationState>
  listAutomationRuns(ruleId?: string): Promise<AutomationRun[]>
  listAutomationLogs(params?: { runId?: string; ruleId?: string }): Promise<AutomationLog[]>
  listAutomationConflicts(projectId?: string): Promise<AutomationConflict[]>
  listApprovals(params?: { pendingOnly?: boolean; projectId?: string }): Promise<ApprovalRequest[]>
  getApproval(id: string): Promise<ApprovalRequest | undefined>
  createApproval(payload: ApprovalCreatePayload): Promise<ApprovalRequest>
  approveApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest>
  rejectApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest>
  requestChangesApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest>
  cancelApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest>
  viewApproval(id: string, actor: string): Promise<ApprovalRequest>
  escalateApproval(id: string, actor: string, escalatedTo: string): Promise<ApprovalRequest>
  resumeApprovedExecution(id: string): Promise<RuntimeExecutionRecord>
  getApprovalHistory(approvalId?: string): Promise<ApprovalHistoryEvent[]>
  listApprovalPolicies(projectId?: string): Promise<ApprovalPolicy[]>
  upsertApprovalPolicy(policy: Partial<ApprovalPolicy> & { name: string }): Promise<ApprovalPolicy>
  listExecutionsWaitingApproval(): Promise<RuntimeExecutionRecord[]>
}
