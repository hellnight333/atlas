import { mockAgentTasks, mockAssets, mockCommands, mockJobs, mockNotifications, mockProjects, mockStudios } from '../mock/data'
import type {
  Agent,
  AgentAssignment,
  AgentMessage,
  AgentCreateRequest,
  AgentMemoryAttachRequest,
  AgentPlanRequest,
  AgentMemoryReference,
  AgentPermission,
  AgentTeam,
  AgentTeamCreateRequest,
  AgentTeamStatusPayload,
  AgentUpdateRequest,
  AssetImportRequest,
  ChatConversation,
  ChatConversationRequest,
  ChatConversationUpdateRequest,
  ChatMessage,
  ChatMessageRequest,
  ImageAsset,
  ImageGenerateRequest,
  ImageGenerationResult,
  ImageVariantRequest,
  ApprovalCreatePayload,
  ApprovalDecisionPayload,
  ApprovalHistoryEvent,
  ApprovalPolicy,
  ApprovalRequest,
  ApprovalState,
  AtlasProvider,
  AutomationConflict,
  AutomationLog,
  AutomationRule,
  AutomationRuleRequest,
  AutomationRuleUpdateRequest,
  AutomationRun,
  AutomationRunRequest,
  AutomationState,
  Capability,
  ContextBundle,
  ExecutionSchedule,
  KnowledgeGraph,
  KnowledgeNode,
  ProjectGraphPayload,
  RuntimeExecutionRecord,
  QueueUpdateResult,
  ResearchGraph,
  ResearchReportRequest,
  ResearchSearchRequest,
  ResearchSession,
  ResearchSessionRequest,
  ResearchSummarizeRequest,
  ReviewComment,
  ReviewCommentRequest,
  ReviewDecisionRequest,
  ReviewHistoryEvent,
  ReviewPublishRequest,
  ReviewSession,
  ReviewSessionRequest,
  ScheduleQueueEntry,
  SearchResult,
  PlannerExecutionPlan,
  SchedulerCreateRequest,
  WorkflowDefinitionPayload,
  WorkspaceContextPayload,
  WorkspaceDashboardPayload,
  WorkspaceRecommendationsPayload,
  WorkspaceRecentPayload,
  WorkflowExecutionPayload,
  WorkflowExecutionRequest,
  WorkflowExecutionResult,
} from '../api/types'

const mockCapabilities: Capability[] = [
  { id: 'cap-research', name: 'Research', studioIds: ['s1'] },
  { id: 'cap-media', name: 'Media', studioIds: ['s2', 's3', 's6'] },
  { id: 'cap-build', name: 'Build', studioIds: ['s4'] },
  { id: 'cap-publish', name: 'Publish', studioIds: ['s5'] },
]

function makeSearchResults(query: string): SearchResult[] {
  const normalized = query.toLowerCase()
  const results: SearchResult[] = []

  for (const project of mockProjects.filter((item) => item.name.toLowerCase().includes(normalized))) {
    results.push({ id: project.id, title: project.name, type: 'project', scope: 'project' })
  }
  for (const asset of mockAssets.filter((item) => item.title.toLowerCase().includes(normalized))) {
    results.push({ id: asset.id, title: asset.title, type: 'asset', scope: 'asset' })
  }
  for (const studio of mockStudios.filter((item) => item.name.toLowerCase().includes(normalized))) {
    results.push({ id: studio.id, title: studio.name, type: 'studio', scope: 'studio' })
  }
  for (const command of mockCommands.filter((item) => item.label.toLowerCase().includes(normalized))) {
    results.push({ id: command.id, title: command.label, type: 'command', scope: command.scope })
  }

  return results
}

export class MockProvider implements AtlasProvider {
  readonly mode = 'mock' as const
  private assets = [...mockAssets]
  private workflows: WorkflowDefinitionPayload[] = []
  private executions: WorkflowExecutionPayload[] = []
  private conversations: ChatConversation[] = []
  private messages: ChatMessage[] = []
  private researchSessions: ResearchSession[] = []
  private researchGraphs: Record<string, ResearchGraph> = {}
  private reviews: ReviewSession[] = []
  private reviewHistory: Record<string, ReviewHistoryEvent[]> = {}
  private agents: Agent[] = []
  private agentMemory: Record<string, AgentMemoryReference[]> = {}
  private schedules: ExecutionSchedule[] = []
  private runtimeExecutions: RuntimeExecutionRecord[] = []
  private agentTeams: AgentTeam[] = []
  private agentTeamMessages: Record<string, AgentMessage[]> = {}
  private knowledgeGraphs: Record<string, ProjectGraphPayload> = {}
  private approvals = new Map<string, ApprovalRequest>()
  private approvalHistory: ApprovalHistoryEvent[] = []
  private approvalPolicies = new Map<string, ApprovalPolicy>()
  private automationRules = new Map<string, AutomationRule>()
  private automationRuns: AutomationRun[] = []
  private automationLogs: AutomationLog[] = []

  async getProjects() {
    return mockProjects
  }

  async getProject(id: string) {
    return mockProjects.find((project) => project.id === id)
  }

  async getAssets() {
    return this.assets
  }

  async getProjectAssets(projectId: string) {
    return this.assets.filter((asset) => asset.projectId === projectId)
  }

  async getAsset(id: string) {
    return this.assets.find((asset) => asset.id === id)
  }

  async importAsset(request: AssetImportRequest) {
    const imported = {
      id: `asset-${Date.now()}`,
      title: request.file.name,
      type: normalizeAssetType(request.assetType, request.file.type, request.file.name),
      projectId: request.projectId,
      freshness: 'authoritative_live' as const,
      version: 1,
      uri: URL.createObjectURL(request.file),
      mimeType: request.file.type,
      fileSize: request.file.size,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      metadata: { original_filename: request.file.name, imported_via: 'desktop' },
      tags: request.tags ?? [],
    }
    this.assets = [imported, ...this.assets]
    return imported
  }

  async deleteAsset(id: string) {
    this.assets = this.assets.filter((asset) => asset.id !== id)
  }

  async getRuns() {
    return mockJobs
  }

  async getActivities() {
    return mockJobs
  }

  async getAgentTasks() {
    return mockAgentTasks
  }

  async getNotifications() {
    return mockNotifications
  }

  async getCapabilities() {
    return mockCapabilities
  }

  async getStudios() {
    return mockStudios
  }

  async getCommands() {
    return mockCommands
  }

  async getWorkflows() {
    return this.workflows
  }

  async getWorkflow(id: string) {
    return this.workflows.find((workflow) => workflow.id === id)
  }

  async createWorkflow(definition: WorkflowDefinitionPayload) {
    this.workflows = [definition, ...this.workflows]
    return definition
  }

  async executeWorkflowDefinition(id: string) {
    const execution: WorkflowExecutionPayload = {
      id: `execution-${Date.now()}`,
      workflow_definition_id: id,
      run_id: `run-${Date.now()}`,
      project_id: 'p1',
      workflow_id: id,
      state: 'completed',
      nodes: {
        import: { node_id: 'import', state: 'completed', attempts: 1, produced_asset_ids: this.assets.slice(0, 1).map((asset) => asset.id) },
      },
    }
    this.executions = [execution, ...this.executions]
    return execution
  }

  async getExecution(id: string) {
    return this.executions.find((execution) => execution.id === id)
  }

  async getExecutionTimeline(id: string) {
    const execution = this.executions.find((item) => item.id === id)
    if (!execution) {
      return []
    }
    return [
      { id: `${id}-start`, type: 'checkpoint', state: 'running', label: 'start' },
      { id: `${id}-end`, type: 'checkpoint', state: execution.state, label: 'end' },
    ]
  }

  async search(query: string) {
    if (!query.trim()) {
      return []
    }
    return makeSearchResults(query)
  }

  async executeWorkflow(_request: WorkflowExecutionRequest): Promise<WorkflowExecutionResult> {
    return { accepted: true, runId: 'mock-run-001' }
  }

  async createChatConversation(request: ChatConversationRequest): Promise<ChatConversation> {
    const conversation: ChatConversation = {
      id: `conversation-${Date.now()}`,
      project_id: request.projectId,
      title: request.title,
      pinned: request.pinned ?? false,
      prompt_version: 0,
      response_version: 0,
      workflow_id: request.workflowId ?? null,
      parent_conversation_id: request.parentConversationId ?? null,
      prompt_asset_id: null,
      response_asset_id: null,
      metadata: request.metadata ?? {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      messages: [],
    }
    this.conversations = [conversation, ...this.conversations]
    return conversation
  }

  async listChatConversations(projectId?: string): Promise<ChatConversation[]> {
    return projectId ? this.conversations.filter((conversation) => conversation.project_id === projectId) : this.conversations
  }

  async getChatConversation(id: string): Promise<ChatConversation | undefined> {
    const conversation = this.conversations.find((item) => item.id === id)
    if (!conversation) {
      return undefined
    }
    return { ...conversation, messages: this.messages.filter((message) => message.conversation_id === id) }
  }

  async sendChatMessage(request: ChatMessageRequest): Promise<ChatMessage> {
    const message: ChatMessage = {
      id: `message-${Date.now()}`,
      conversation_id: request.conversationId,
      version: this.messages.filter((item) => item.conversation_id === request.conversationId).length + 1,
      role: request.role,
      content: request.content,
      asset_id: request.assetId ?? null,
      prompt_asset_id: request.promptAssetId ?? null,
      response_asset_id: request.responseAssetId ?? null,
      provider_name: request.providerName ?? null,
      execution_time_ms: request.executionTimeMs ?? null,
      tokens: request.tokens ?? null,
      metadata: request.metadata ?? {},
      created_at: new Date().toISOString(),
    }
    this.messages = [...this.messages, message]
    return message
  }

  async updateChatConversation(id: string, request: ChatConversationUpdateRequest): Promise<ChatConversation> {
    const existing = this.conversations.find((item) => item.id === id)
    if (!existing) {
      throw new Error('Conversation not found')
    }
    const updated: ChatConversation = {
      ...existing,
      title: request.title ?? existing.title,
      pinned: request.pinned ?? existing.pinned,
      provider_name: request.providerName ?? existing.provider_name,
      execution_time_ms: request.executionTimeMs ?? existing.execution_time_ms,
      tokens: request.tokens ?? existing.tokens,
      workflow_id: request.workflowId ?? existing.workflow_id,
      parent_conversation_id: request.parentConversationId ?? existing.parent_conversation_id,
      prompt_asset_id: request.promptAssetId ?? existing.prompt_asset_id,
      response_asset_id: request.responseAssetId ?? existing.response_asset_id,
      metadata: request.metadata ?? existing.metadata,
      updated_at: new Date().toISOString(),
    }
    this.conversations = this.conversations.map((item) => (item.id === id ? updated : item))
    return updated
  }

  async deleteChatConversation(id: string): Promise<void> {
    this.conversations = this.conversations.filter((item) => item.id !== id)
    this.messages = this.messages.filter((item) => item.conversation_id !== id)
  }

  async createResearchSession(request: ResearchSessionRequest): Promise<ResearchSession> {
    const session: ResearchSession = {
      id: `research-session-${Date.now()}`,
      project_id: request.projectId,
      title: request.title,
      question: request.question,
      status: 'active',
      conversation_id: request.conversationId ?? null,
      collection_asset_id: null,
      report_asset_id: null,
      metadata: request.metadata ?? {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    this.researchSessions = [session, ...this.researchSessions]
    return session
  }

  async listResearchSessions(projectId?: string): Promise<ResearchSession[]> {
    return projectId ? this.researchSessions.filter((session) => session.project_id === projectId) : this.researchSessions
  }

  async getResearchSession(id: string): Promise<ResearchSession | undefined> {
    return this.researchSessions.find((session) => session.id === id)
  }

  async searchResearch(request: ResearchSearchRequest): Promise<{ session_id: string; provider: string; sources: Array<Record<string, unknown>> }> {
    const sources = Array.from({ length: 3 }, (_, index) => ({
      id: `source-${Date.now()}-${index}`,
      title: `${request.query} source ${index + 1}`,
      uri: `https://example.com/${index + 1}`,
      project_id: 'p1',
      metadata: {
        kind: 'source',
        provider: request.provider ?? 'mock-search',
        title: `${request.query} source ${index + 1}`,
        author: 'Mock Research Provider',
        language: 'en',
        content_type: 'text/html',
        trust_score: 0.7,
      },
    }))
    return { session_id: request.sessionId, provider: request.provider ?? 'mock-search', sources }
  }

  async summarizeResearch(request: ResearchSummarizeRequest): Promise<{ run_id: string; job_id: string; provider: string; asset: Record<string, unknown> }> {
    return {
      run_id: `run-${Date.now()}`,
      job_id: `job-${Date.now()}`,
      provider: 'local-text',
      asset: {
        id: `finding-${Date.now()}`,
        metadata: {
          kind: 'finding',
          content: `Summary for ${request.prompt ?? 'research session'}`,
          citations: request.sourceAssetIds,
        },
      },
    }
  }

  async generateResearchReport(request: ResearchReportRequest): Promise<Record<string, unknown>> {
    return {
      id: `report-${Date.now()}`,
      metadata: {
        kind: 'report',
        format: request.format ?? 'markdown',
        content: 'Mock research report',
      },
    }
  }

  async getResearchGraph(projectId: string): Promise<ResearchGraph> {
    return this.researchGraphs[projectId] ?? {
      project_id: projectId,
      nodes: [],
      edges: [],
      updated_at: new Date().toISOString(),
    }
  }

  async createReviewSession(request: ReviewSessionRequest): Promise<ReviewSession> {
    const review: ReviewSession = {
      id: `review-${Date.now()}`,
      project_id: request.projectId,
      title: request.title,
      status: 'pending',
      asset_id: request.assetId ?? null,
      published_asset_id: null,
      workflow_id: request.workflowId ?? null,
      metadata: request.metadata ?? {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      items: request.assetId
        ? [
            {
              id: `review-item-${Date.now()}`,
              review_id: `review-${Date.now()}`,
              asset_id: request.assetId,
              decision: 'pending',
              comment: null,
              metadata: {},
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            },
          ]
        : [],
      comments: [],
    }
    this.reviews = [review, ...this.reviews]
    this.reviewHistory[review.id] = [
      {
        id: `review-event-${Date.now()}`,
        review_id: review.id,
        event_type: 'created',
        actor: 'system',
        from_status: null,
        to_status: 'pending',
        asset_id: review.asset_id ?? null,
        published_asset_id: null,
        metadata: {},
        created_at: new Date().toISOString(),
      },
    ]
    return review
  }

  async listReviewSessions(projectId?: string): Promise<ReviewSession[]> {
    return projectId ? this.reviews.filter((review) => review.project_id === projectId) : this.reviews
  }

  async approveReview(id: string, request: ReviewDecisionRequest): Promise<ReviewSession> {
    const review = this.reviews.find((item) => item.id === id)
    if (!review) {
      throw new Error('Review not found')
    }
    const updated: ReviewSession = {
      ...review,
      status: 'approved',
      asset_id: request.assetId,
      updated_at: new Date().toISOString(),
      items: [
        {
          id: `review-item-${request.assetId}`,
          review_id: id,
          asset_id: request.assetId,
          decision: 'approved',
          comment: request.comment ?? null,
          metadata: request.metadata ?? {},
          created_at: review.created_at,
          updated_at: new Date().toISOString(),
        },
      ],
    }
    this.reviews = this.reviews.map((item) => (item.id === id ? updated : item))
    this.reviewHistory[id] = [
      ...(this.reviewHistory[id] ?? []),
      {
        id: `review-event-${Date.now()}`,
        review_id: id,
        event_type: 'approved',
        actor: 'system',
        comment: request.comment ?? null,
        from_status: review.status,
        to_status: 'approved',
        asset_id: request.assetId,
        published_asset_id: null,
        metadata: request.metadata ?? {},
        created_at: new Date().toISOString(),
      },
    ]
    return updated
  }

  async rejectReview(id: string, request: ReviewDecisionRequest): Promise<ReviewSession> {
    const review = this.reviews.find((item) => item.id === id)
    if (!review) {
      throw new Error('Review not found')
    }
    const updated: ReviewSession = {
      ...review,
      status: 'changes_requested',
      asset_id: request.assetId,
      updated_at: new Date().toISOString(),
      items: [
        {
          id: `review-item-${request.assetId}`,
          review_id: id,
          asset_id: request.assetId,
          decision: 'rejected',
          comment: request.comment ?? null,
          metadata: request.metadata ?? {},
          created_at: review.created_at,
          updated_at: new Date().toISOString(),
        },
      ],
    }
    this.reviews = this.reviews.map((item) => (item.id === id ? updated : item))
    this.reviewHistory[id] = [
      ...(this.reviewHistory[id] ?? []),
      {
        id: `review-event-${Date.now()}`,
        review_id: id,
        event_type: 'rejected',
        actor: 'system',
        comment: request.comment ?? null,
        from_status: review.status,
        to_status: 'changes_requested',
        asset_id: request.assetId,
        published_asset_id: null,
        metadata: request.metadata ?? {},
        created_at: new Date().toISOString(),
      },
    ]
    return updated
  }

  async commentReview(id: string, request: ReviewCommentRequest): Promise<ReviewComment> {
    const review = this.reviews.find((item) => item.id === id)
    if (!review) {
      throw new Error('Review not found')
    }
    const comment: ReviewComment = {
      id: `review-comment-${Date.now()}`,
      review_id: id,
      content: request.content,
      metadata: request.metadata ?? {},
      created_at: new Date().toISOString(),
    }
    this.reviews = this.reviews.map((item) =>
      item.id === id
        ? { ...item, comments: [...(item.comments ?? []), comment], updated_at: new Date().toISOString() }
        : item,
    )
    this.reviewHistory[id] = [
      ...(this.reviewHistory[id] ?? []),
      {
        id: `review-event-${Date.now()}`,
        review_id: id,
        event_type: 'commented',
        actor: 'system',
        comment: request.content,
        from_status: review.status,
        to_status: review.status,
        asset_id: review.asset_id ?? null,
        published_asset_id: null,
        metadata: request.metadata ?? {},
        created_at: new Date().toISOString(),
      },
    ]
    return comment
  }

  async publishReview(id: string, request: ReviewPublishRequest): Promise<Record<string, unknown>> {
    const review = this.reviews.find((item) => item.id === id)
    if (!review) {
      throw new Error('Review not found')
    }
    const publishedAssetId = `published-${request.assetId}-${Date.now()}`
    const updated: ReviewSession = {
      ...review,
      status: 'published',
      asset_id: request.assetId,
      published_asset_id: publishedAssetId,
      updated_at: new Date().toISOString(),
    }
    this.reviews = this.reviews.map((item) => (item.id === id ? updated : item))
    this.reviewHistory[id] = [
      ...(this.reviewHistory[id] ?? []),
      {
        id: `review-event-${Date.now()}`,
        review_id: id,
        event_type: 'published',
        actor: 'system',
        from_status: review.status,
        to_status: 'published',
        asset_id: request.assetId,
        published_asset_id: publishedAssetId,
        metadata: request.metadata ?? {},
        created_at: new Date().toISOString(),
      },
    ]
    return {
      ...updated,
      published_asset: {
        id: publishedAssetId,
        parent_asset_id: request.assetId,
        version: 2,
      },
    }
  }

  async getReviewHistory(id: string): Promise<ReviewHistoryEvent[]> {
    return this.reviewHistory[id] ?? []
  }

  async generateImage(request: ImageGenerateRequest): Promise<ImageGenerationResult> {
    return this.createImageFromRequest(request.projectId, request)
  }

  async listImages(projectId?: string): Promise<ImageAsset[]> {
    const images = this.assets.filter((asset) => asset.type === 'Image')
    const scoped = projectId ? images.filter((asset) => asset.projectId === projectId) : images
    return scoped.map((asset) => this.toImageAsset(asset))
  }

  async getImage(id: string): Promise<ImageAsset | undefined> {
    const asset = this.assets.find((item) => item.id === id && item.type === 'Image')
    return asset ? this.toImageAsset(asset) : undefined
  }

  async createImageVariant(id: string, request: ImageVariantRequest): Promise<ImageGenerationResult> {
    const base = this.assets.find((item) => item.id === id && item.type === 'Image')
    if (!base) {
      throw new Error('Image not found')
    }
    return this.createImageFromRequest(base.projectId, request, base)
  }

  async regenerateImage(id: string, request: ImageVariantRequest): Promise<ImageGenerationResult> {
    const base = this.assets.find((item) => item.id === id && item.type === 'Image')
    if (!base) {
      throw new Error('Image not found')
    }
    return this.createImageFromRequest(base.projectId, request, base)
  }

  async getImageVersions(id: string): Promise<ImageAsset[]> {
    const base = this.assets.find((item) => item.id === id && item.type === 'Image')
    if (!base) {
      return []
    }
    const rootId = (base.metadata?.parent_asset_id as string | undefined) ?? base.id
    const versions = this.assets
      .filter((asset) => asset.type === 'Image')
      .filter((asset) => asset.id === rootId || (asset.metadata?.parent_asset_id as string | undefined) === rootId)
      .sort((a, b) => (a.version ?? 1) - (b.version ?? 1))
    return versions.map((asset) => this.toImageAsset(asset))
  }

  private createImageFromRequest(
    projectId: string,
    request: ImageGenerateRequest | ImageVariantRequest,
    base?: (typeof mockAssets)[number],
  ): ImageGenerationResult {
    const now = new Date().toISOString()
    const parentVersion = base?.version ?? 0
    const parentPrompt = typeof base?.metadata?.prompt === 'string' ? base.metadata.prompt : ''
    const prompt = request.prompt ?? parentPrompt ?? 'Mock image generation'
    const imageId = `image-${Date.now()}`
    const runId = `run-${Date.now()}`
    const jobId = `job-${Date.now()}`
    const version = parentVersion + 1
    const parentId = base?.id ?? null
    const promptHistoryBase = Array.isArray(base?.metadata?.prompt_history)
      ? (base?.metadata?.prompt_history as string[])
      : []
    const promptHistory = [...promptHistoryBase, prompt].slice(-20)

    const imageLikeAsset = {
      id: imageId,
      title: `Image v${version}`,
      type: 'Image' as const,
      projectId,
      freshness: 'authoritative_live' as const,
      version,
      uri: `https://mock.atlas/images/${imageId}`,
      mimeType: 'image/png',
      fileSize: 0,
      contentHash: `hash-${imageId}`,
      createdAt: now,
      updatedAt: now,
      metadata: {
        prompt,
        negative_prompt: request.negativePrompt ?? (base?.metadata?.negative_prompt as string | undefined) ?? '',
        styles: request.styles ?? (base?.metadata?.styles as string[] | undefined) ?? [],
        template: request.template ?? (base?.metadata?.template as string | undefined) ?? null,
        variables: request.variables ?? (base?.metadata?.variables as Record<string, unknown> | undefined) ?? {},
        prompt_history: promptHistory,
        prompt_version: promptHistory.length,
        seed: request.seed ?? (base?.metadata?.seed as number | undefined) ?? 42,
        steps: request.steps ?? (base?.metadata?.steps as number | undefined) ?? 30,
        cfg: request.cfg ?? (base?.metadata?.cfg as number | undefined) ?? 7,
        resolution: request.resolution ?? (base?.metadata?.resolution as string | undefined) ?? '1024x1024',
        sampler: request.sampler ?? (base?.metadata?.sampler as string | undefined) ?? 'euler',
        provider: request.provider ?? (base?.metadata?.provider as string | undefined) ?? 'mock-provider',
        workflow: request.workflow ?? (base?.metadata?.workflow as string | undefined) ?? 'image.generate',
        model: request.model ?? (base?.metadata?.model as string | undefined) ?? 'mock-flux',
        execution_time_ms: 1200,
        parent_asset_id: parentId,
      },
      tags: ['image-generated'],
    }

    this.assets = [imageLikeAsset, ...this.assets]
    return {
      run: { id: runId, project_id: projectId, status: 'completed' },
      job: { id: jobId, run_id: runId, status: 'completed', provider: 'mock-provider' },
      image: this.toImageAsset(imageLikeAsset),
    }
  }

  private toImageAsset(asset: (typeof mockAssets)[number]): ImageAsset {
    const metadata = (asset.metadata ?? {}) as Record<string, unknown>
    return {
      id: asset.id,
      project_id: asset.projectId,
      run_id: null,
      job_id: null,
      workflow_id: (metadata.workflow as string | undefined) ?? null,
      parent_asset_id: (metadata.parent_asset_id as string | undefined) ?? null,
      version: asset.version,
      uri: asset.uri,
      thumbnail_uri: asset.uri,
      content_hash: asset.contentHash ?? null,
      prompt: (metadata.prompt as string | undefined) ?? '',
      negative_prompt: (metadata.negative_prompt as string | undefined) ?? '',
      styles: Array.isArray(metadata.styles) ? (metadata.styles as string[]) : [],
      template: (metadata.template as string | undefined) ?? null,
      variables: (metadata.variables as Record<string, unknown> | undefined) ?? {},
      prompt_history: Array.isArray(metadata.prompt_history) ? (metadata.prompt_history as string[]) : [],
      prompt_version: (metadata.prompt_version as number | undefined) ?? 1,
      seed: (metadata.seed as number | undefined) ?? null,
      steps: (metadata.steps as number | undefined) ?? null,
      cfg: (metadata.cfg as number | undefined) ?? null,
      resolution: (metadata.resolution as string | undefined) ?? null,
      sampler: (metadata.sampler as string | undefined) ?? null,
      provider: (metadata.provider as string | undefined) ?? 'mock-provider',
      workflow: (metadata.workflow as string | undefined) ?? 'image.generate',
      model: (metadata.model as string | undefined) ?? 'mock-flux',
      execution_time_ms: (metadata.execution_time_ms as number | undefined) ?? null,
      metadata,
      created_at: asset.createdAt,
      updated_at: asset.updatedAt,
    }
  }

  async getWorkspaceContext(projectId: string): Promise<WorkspaceContextPayload> {
    const assets = this.assets.filter((asset) => asset.projectId === projectId)
    const reviews = this.reviews.filter((review) => review.project_id === projectId)
    const conversations = this.conversations.filter((conversation) => conversation.project_id === projectId)
    const researchSessions = this.researchSessions.filter((session) => session.project_id === projectId)

    return {
      workspace_context: {
        project: mockProjects.find((project) => project.id === projectId) ?? { id: projectId },
        project_summary: {
          total_assets: assets.length,
          open_reviews: reviews.filter((review) => review.status !== 'published').length,
          conversations: conversations.length,
          research_sessions: researchSessions.length,
        },
        recent_activity: mockJobs.slice(0, 10).map((job) => ({
          id: job.id,
          action: job.name,
          status: job.state,
          created_at: new Date().toISOString(),
        })),
        recent_assets: assets.slice(0, 10),
        pinned_assets: assets.filter((asset) => Boolean(asset.metadata?.pinned)).slice(0, 10),
        open_tasks: mockJobs
          .filter((job) => ['running', 'blocked'].includes(job.state))
          .slice(0, 10)
          .map((job) => ({ id: job.id, action: job.name, status: job.state, run_id: job.id })),
        suggested_tasks: [
          {
            type: 'review_pending_asset',
            title: 'Review Pending Asset',
            reason: 'Recent generated outputs are waiting for review.',
            action: 'open-review-studio',
            reference_id: reviews[0]?.id,
          },
          {
            type: 'generate_variant',
            title: 'Generate Variant',
            reason: 'Iterate on your latest image to explore alternatives.',
            action: 'open-image-studio',
            reference_id: assets.find((asset) => asset.type === 'Image')?.id,
          },
        ],
        recent_conversations: conversations.slice(0, 10),
        recent_research: researchSessions.slice(0, 10),
        recent_reviews: reviews.slice(0, 10),
        recent_images: assets.filter((asset) => asset.type === 'Image').slice(0, 10),
        knowledge_highlights: assets.slice(0, 5).map((asset) => ({
          asset_id: asset.id,
          title: asset.title,
          summary: String(asset.metadata?.summary ?? 'No summary yet.'),
          kind: asset.type,
        })),
        recommendations: [
          {
            type: 'continue_research',
            title: 'Continue Research',
            reason: 'Research sessions exist and can be extended.',
            action: 'open-research',
            reference_id: researchSessions[0]?.id,
          },
          {
            type: 'publish',
            title: 'Publish',
            reason: 'Approved reviews can be published.',
            action: 'publish-review',
            reference_id: reviews.find((review) => review.status === 'approved')?.id,
          },
        ],
      },
    }
  }

  async getWorkspaceRecommendations(projectId: string): Promise<WorkspaceRecommendationsPayload> {
    const context = await this.getWorkspaceContext(projectId)
    return {
      project_id: projectId,
      recommendations: context.workspace_context.recommendations,
    }
  }

  async getWorkspaceRecent(projectId: string): Promise<WorkspaceRecentPayload> {
    const context = await this.getWorkspaceContext(projectId)
    return {
      project_id: projectId,
      recent_activity: context.workspace_context.recent_activity,
      recent_assets: context.workspace_context.recent_assets,
      recent_conversations: context.workspace_context.recent_conversations,
      recent_research: context.workspace_context.recent_research,
      recent_reviews: context.workspace_context.recent_reviews,
      recent_images: context.workspace_context.recent_images,
      recent_workflows: this.workflows.slice(0, 10),
      recent_runs: mockJobs.slice(0, 10).map((job) => ({
        id: job.id,
        title: job.name,
        state: job.state,
      })),
    }
  }

  async getWorkspaceDashboard(projectId: string): Promise<WorkspaceDashboardPayload> {
    const context = await this.getWorkspaceContext(projectId)
    const health = {
      running_jobs: context.workspace_context.open_tasks.filter((task) => task.status === 'running').length,
      blocked_jobs: context.workspace_context.open_tasks.filter((task) => task.status === 'blocked').length,
      open_reviews: context.workspace_context.recent_reviews.filter((review) => review.status !== 'published').length,
      research_sessions: context.workspace_context.recent_research.length,
      image_queue: context.workspace_context.recent_images.length,
    }
    return {
      project_summary: {
        project: context.workspace_context.project,
        summary: `${context.workspace_context.recent_assets.length} recent assets and ${context.workspace_context.recent_activity.length} activities`,
      },
      project_health: health,
      recent_timeline: [
        ...context.workspace_context.recent_assets.map((asset) => ({
          id: String(asset.id ?? ''),
          type: 'asset',
          title: String(asset.title ?? asset.id ?? 'asset'),
          created_at: String(asset.createdAt ?? new Date().toISOString()),
        })),
        ...context.workspace_context.recent_activity.map((activity) => ({
          id: String(activity.id ?? ''),
          type: 'activity',
          title: String(activity.action ?? activity.id ?? 'activity'),
          created_at: String(activity.created_at ?? new Date().toISOString()),
        })),
      ].slice(0, 20),
      recent_workflows: this.workflows.slice(0, 10),
      research_progress: {
        total_sessions: context.workspace_context.recent_research.length,
        active_sessions: context.workspace_context.recent_research.length,
      },
      review_queue: context.workspace_context.recent_reviews.filter((review) => review.status !== 'published'),
      image_queue: context.workspace_context.recent_images,
      knowledge_growth: {
        research_assets: context.workspace_context.recent_research.length,
        conversations: context.workspace_context.recent_conversations.length,
        research_sessions: context.workspace_context.recent_research.length,
      },
    }
  }

  async listAgents(projectId?: string): Promise<Agent[]> {
    if (!projectId) {
      return this.agents
    }
    return this.agents.filter((agent) => agent.project_id === projectId)
  }

  async getAgent(id: string): Promise<Agent | undefined> {
    return this.agents.find((agent) => agent.id === id)
  }

  async createAgent(request: AgentCreateRequest): Promise<Agent> {
    const now = new Date().toISOString()
    const agent: Agent = {
      id: `agent-${Date.now()}`,
      name: request.name,
      description: request.description ?? '',
      role: request.role,
      workspace_id: request.workspaceId ?? null,
      project_id: request.projectId ?? null,
      capabilities: request.capabilities ?? [],
      status: request.status ?? 'idle',
      memory_id: request.memoryId ?? `agent-memory-${Date.now()}`,
      permission_set: request.permissionSet ?? [],
      created_at: now,
      updated_at: now,
    }
    this.agents = [agent, ...this.agents]
    this.agentMemory[agent.id] = []
    return agent
  }

  async updateAgent(id: string, request: AgentUpdateRequest): Promise<Agent> {
    const existing = this.agents.find((agent) => agent.id === id)
    if (!existing) {
      throw new Error('Agent not found')
    }
    const updated: Agent = {
      ...existing,
      name: request.name ?? existing.name,
      description: request.description ?? existing.description,
      role: request.role ?? existing.role,
      workspace_id: request.workspaceId ?? existing.workspace_id,
      project_id: request.projectId ?? existing.project_id,
      capabilities: request.capabilities ?? existing.capabilities,
      status: request.status ?? existing.status,
      memory_id: request.memoryId ?? existing.memory_id,
      permission_set: request.permissionSet ?? existing.permission_set,
      updated_at: new Date().toISOString(),
    }
    this.agents = this.agents.map((agent) => (agent.id === id ? updated : agent))
    return updated
  }

  async deleteAgent(id: string): Promise<void> {
    this.agents = this.agents.filter((agent) => agent.id !== id)
    delete this.agentMemory[id]
  }

  async listAgentMemory(id: string): Promise<AgentMemoryReference[]> {
    return this.agentMemory[id] ?? []
  }

  async attachAgentMemory(id: string, request: AgentMemoryAttachRequest): Promise<AgentMemoryReference> {
    const agent = this.agents.find((item) => item.id === id)
    if (!agent) {
      throw new Error('Agent not found')
    }
    const reference: AgentMemoryReference = {
      id: `memory-ref-${Date.now()}`,
      memory_id: agent.memory_id,
      agent_id: id,
      kind: request.kind,
      asset_id: request.assetId,
      created_at: new Date().toISOString(),
    }
    this.agentMemory[id] = [reference, ...(this.agentMemory[id] ?? [])]
    return reference
  }

  async getAgentPermissions(id: string): Promise<AgentPermission[]> {
    const agent = this.agents.find((item) => item.id === id)
    if (!agent) {
      return []
    }
    return agent.permission_set
  }

  async generateAgentPlan(id: string, request: AgentPlanRequest): Promise<PlannerExecutionPlan> {
    const agent = this.agents.find((item) => item.id === id)
    if (!agent) {
      throw new Error('Agent not found')
    }
    const now = new Date().toISOString()
    const baseStepId = `${id}-plan-step-${Date.now()}`
    const steps = [
      {
        id: `${baseStepId}-1`,
        description: `Research and frame goal: ${request.goal}`,
        capability: 'research',
        action: 'text.generate',
        payload: { prompt: `research: ${request.goal}` },
        expected_output: 'goal-brief',
        dependencies: [],
        estimated_cost_usd: 0.01,
        estimated_time_seconds: 45,
        review_required: false,
        estimate: {
          tokens: 900,
          gpu_seconds: 0,
          provider_class: 'planner-simulated-search',
          latency_seconds: 45,
          overall_cost_usd: 0.01,
        },
      },
      {
        id: `${baseStepId}-2`,
        description: `Compose execution-ready workflow plan`,
        capability: 'workflow',
        action: 'text.generate',
        payload: { prompt: `workflow: ${request.goal}` },
        expected_output: 'workflow-plan',
        dependencies: [`${baseStepId}-1`],
        estimated_cost_usd: 0.02,
        estimated_time_seconds: 60,
        review_required: true,
        estimate: {
          tokens: 1600,
          gpu_seconds: 0,
          provider_class: 'planner-simulated-llm',
          latency_seconds: 60,
          overall_cost_usd: 0.02,
        },
      },
    ]

    return {
      plan_id: `plan-${Date.now()}`,
      goal: request.goal,
      confidence: 0.72,
      estimated_duration_seconds: steps.reduce((acc, item) => acc + item.estimated_time_seconds, 0),
      estimated_cost_usd: Number(steps.reduce((acc, item) => acc + item.estimated_cost_usd, 0).toFixed(4)),
      steps,
      dependencies: [{ from: `${baseStepId}-1`, to: `${baseStepId}-2` }],
      capabilities_required: ['research', 'workflow'],
      assets_required: this.assets.slice(0, 2).map((asset) => asset.id),
      expected_outputs: ['goal-brief', 'workflow-plan'],
      review_required: true,
      context_snapshot: {
        project_summary: { total_assets: this.assets.length },
        running_jobs: mockJobs.filter((job) => job.state === 'running').length,
      },
      created_at: now,
    }
  }

  async createSchedule(request: SchedulerCreateRequest): Promise<ExecutionSchedule> {
    const plan = await this.generateAgentPlan(request.agentId, { goal: request.goal })
    const now = new Date().toISOString()
    const queueEntries: ScheduleQueueEntry[] = plan.steps.map((step, index) => ({
      id: `schedule-entry-${Date.now()}-${index}`,
      plan_step: step,
      status: step.dependencies.length === 0 ? 'ready' : 'queued',
      priority: request.priority ?? 'normal',
      dependencies: step.dependencies,
      executor_hint: request.availableExecutors?.[0] ?? null,
      capability: step.capability,
      retry_count: 0,
      scheduled_time: now,
      started_time: null,
      completed_time: null,
    }))
    const schedule: ExecutionSchedule = {
      schedule_id: `schedule-${Date.now()}`,
      plan_id: plan.plan_id,
      agent_id: request.agentId,
      created_at: now,
      priority: request.priority ?? 'normal',
      estimated_finish_time: new Date(Date.now() + plan.estimated_duration_seconds * 1000).toISOString(),
      queue_entries: queueEntries,
      blocked_entries: queueEntries.filter((entry) => entry.dependencies.length > 0).map((entry) => entry.id),
      parallel_groups: [queueEntries.map((entry) => entry.plan_step.id)],
      resume_tokens: [],
      queue_metadata: {
        available_executors: request.availableExecutors ?? [],
        execution_policy: request.executionPolicy ?? {},
      },
    }
    this.schedules = [schedule, ...this.schedules]
    return schedule
  }

  async getSchedule(id: string): Promise<ExecutionSchedule> {
    const schedule = this.schedules.find((item) => item.schedule_id === id)
    if (!schedule) {
      throw new Error('Schedule not found')
    }
    return schedule
  }

  async getScheduleQueue(id: string): Promise<ScheduleQueueEntry[]> {
    const schedule = await this.getSchedule(id)
    return schedule.queue_entries
  }

  async pauseSchedule(id: string): Promise<QueueUpdateResult> {
    const schedule = await this.getSchedule(id)
    const updatedEntries = schedule.queue_entries
      .filter((entry) => ['queued', 'ready', 'running'].includes(entry.status))
      .map((entry) => {
        entry.status = 'paused'
        return entry.id
      })
    return { schedule_id: id, updated_entries: updatedEntries, status: 'ok' }
  }

  async resumeSchedule(id: string): Promise<QueueUpdateResult> {
    const schedule = await this.getSchedule(id)
    const updatedEntries = schedule.queue_entries
      .filter((entry) => entry.status === 'paused')
      .map((entry) => {
        entry.status = entry.dependencies.length === 0 ? 'ready' : 'queued'
        return entry.id
      })
    return { schedule_id: id, updated_entries: updatedEntries, status: 'ok' }
  }

  async cancelSchedule(id: string): Promise<QueueUpdateResult> {
    const schedule = await this.getSchedule(id)
    const now = new Date().toISOString()
    const updatedEntries = schedule.queue_entries
      .filter((entry) => !['completed', 'cancelled'].includes(entry.status))
      .map((entry) => {
        entry.status = 'cancelled'
        entry.completed_time = now
        return entry.id
      })
    return { schedule_id: id, updated_entries: updatedEntries, status: 'ok' }
  }

  async startRuntimeSchedule(id: string): Promise<RuntimeExecutionRecord[]> {
    const schedule = await this.getSchedule(id)
    const now = new Date().toISOString()
    const readyEntries = schedule.queue_entries.filter((entry) => entry.status === 'ready')
    const executions = readyEntries.map((entry, index) => {
      const terminalStatus = index === 0 ? 'completed' : 'running'
      const execution: RuntimeExecutionRecord = {
        execution_id: `runtime-${Date.now()}-${index}`,
        schedule_id: schedule.schedule_id,
        entry_id: entry.id,
        agent_id: schedule.agent_id,
        plan_id: schedule.plan_id,
        action: entry.plan_step.action,
        payload: entry.plan_step.payload,
        status: terminalStatus,
        attempts: 1,
        retry_policy: { max_attempts: 2, retry_delay: 0, backoff: 1 },
        created_at: now,
        updated_at: now,
        started_at: now,
        heartbeat_at: now,
        deadline_at: new Date(Date.now() + 30_000).toISOString(),
        completed_at: terminalStatus === 'completed' ? now : null,
        timeout_reason: null,
        error: null,
        provider_name: terminalStatus === 'completed' ? 'mock-provider' : null,
        run_id: `run-${Date.now()}-${index}`,
        job_id: `job-${Date.now()}-${index}`,
        asset_id: terminalStatus === 'completed' ? this.assets[0]?.id ?? null : null,
        output: terminalStatus === 'completed' ? { result: 'ok' } : {},
        cancellation_requested: false,
        timeline: [
          { status: 'queued', timestamp: now },
          { status: 'preparing', timestamp: now },
          { status: terminalStatus, timestamp: now, attempt: 1 },
        ],
      }
      entry.status = terminalStatus === 'completed' ? 'completed' : 'running'
      entry.started_time = now
      entry.completed_time = terminalStatus === 'completed' ? now : null
      return execution
    })
    this.runtimeExecutions = [...executions, ...this.runtimeExecutions]
    return executions
  }

  async listRuntime(): Promise<RuntimeExecutionRecord[]> {
    return this.runtimeExecutions
  }

  async listRuntimeRunning(): Promise<RuntimeExecutionRecord[]> {
    return this.runtimeExecutions.filter((item) => ['pending', 'queued', 'preparing', 'running'].includes(item.status))
  }

  async listRuntimeHistory(): Promise<RuntimeExecutionRecord[]> {
    return this.runtimeExecutions.filter((item) => ['completed', 'failed', 'cancelled', 'timed_out'].includes(item.status))
  }

  async getRuntimeExecution(id: string): Promise<RuntimeExecutionRecord | undefined> {
    return this.runtimeExecutions.find((item) => item.execution_id === id)
  }

  async cancelRuntimeExecution(id: string): Promise<RuntimeExecutionRecord> {
    const existing = this.runtimeExecutions.find((item) => item.execution_id === id)
    if (!existing) {
      throw new Error('Runtime execution not found')
    }
    existing.status = 'cancelled'
    existing.cancellation_requested = true
    existing.updated_at = new Date().toISOString()
    existing.completed_at = existing.updated_at
    existing.timeline = [...existing.timeline, { status: 'cancelled', timestamp: existing.updated_at }]
    return existing
  }

  async retryRuntimeExecution(id: string): Promise<RuntimeExecutionRecord> {
    const existing = this.runtimeExecutions.find((item) => item.execution_id === id)
    if (!existing) {
      throw new Error('Runtime execution not found')
    }
    const now = new Date().toISOString()
    const retried: RuntimeExecutionRecord = {
      ...existing,
      execution_id: `runtime-retry-${Date.now()}`,
      status: 'completed',
      attempts: existing.attempts + 1,
      created_at: now,
      updated_at: now,
      started_at: now,
      heartbeat_at: now,
      completed_at: now,
      cancellation_requested: false,
      error: null,
      output: { result: 'retried-ok' },
      timeline: [
        ...existing.timeline,
        { status: 'queued', timestamp: now, attempt: existing.attempts + 1 },
        { status: 'completed', timestamp: now, attempt: existing.attempts + 1 },
      ],
    }
    this.runtimeExecutions = [retried, ...this.runtimeExecutions]
    return retried
  }

  async createAgentTeam(request: AgentTeamCreateRequest): Promise<AgentTeam> {
    const now = new Date().toISOString()
    const assignments: AgentAssignment[] = request.assignments.map((assignment, index) => {
      const resourceLimits: Record<string, number> =
        assignment.role === 'image' || assignment.role === 'video'
          ? { max_gpu_jobs: 1 }
          : { max_cpu_jobs: 1 }

      return {
      id: `assignment-${Date.now()}-${index}`,
      team_id: `team-${Date.now()}`,
      agent_id: assignment.agentId,
      role: assignment.role,
      title: assignment.title,
      status: (assignment.dependencies?.length ? 'waiting' : 'completed'),
      capabilities: [assignment.role],
      allowed_actions: [assignment.action],
      permissions: ['read_assets'],
      resource_limits: resourceLimits,
      action: assignment.action,
      payload: assignment.payload ?? {},
      dependencies: assignment.dependencies ?? [],
      mailbox_id: assignment.agentId,
      schedule_id: null,
      runtime_execution_id: null,
      result_asset_id: assignment.dependencies?.length ? null : this.assets[0]?.id ?? null,
      error: null,
      created_at: now,
      updated_at: now,
    }})
    const teamId = assignments[0]?.team_id ?? `team-${Date.now()}`
    const team: AgentTeam = {
      id: teamId,
      name: request.name,
      project_id: request.projectId ?? null,
      workspace_id: request.workspaceId ?? null,
      status: assignments.every((item) => item.status === 'completed') ? 'completed' : 'running',
      assignments: assignments.map((item) => ({ ...item, team_id: teamId })),
      conversation_ids: [],
      created_at: now,
      updated_at: now,
    }
    this.agentTeams = [team, ...this.agentTeams]
    this.agentTeamMessages[teamId] = team.assignments.map((assignment, index) => ({
      id: `message-${Date.now()}-${index}`,
      sender: 'coordinator',
      receiver: assignment.agent_id,
      timestamp: now,
      type: 'TaskAssignment',
      payload: {
        assignment_id: assignment.id,
        title: assignment.title,
        action: assignment.action,
      },
      correlation_id: teamId,
      reply_to: null,
    }))
    return team
  }

  async getAgentTeam(id: string): Promise<AgentTeam | undefined> {
    return this.agentTeams.find((team) => team.id === id)
  }

  async getAgentTeamMessages(id: string): Promise<AgentMessage[]> {
    return this.agentTeamMessages[id] ?? []
  }

  async cancelAgentTeam(id: string): Promise<AgentTeam> {
    const team = this.agentTeams.find((item) => item.id === id)
    if (!team) {
      throw new Error('Team not found')
    }
    const updated: AgentTeam = {
      ...team,
      status: 'cancelled',
      updated_at: new Date().toISOString(),
      assignments: team.assignments.map((assignment) => ({
        ...assignment,
        status: assignment.status === 'completed' ? assignment.status : 'cancelled',
        updated_at: new Date().toISOString(),
      })),
    }
    this.agentTeams = this.agentTeams.map((item) => (item.id === id ? updated : item))
    return updated
  }

  async getAgentTeamStatus(id: string): Promise<AgentTeamStatusPayload> {
    const team = this.agentTeams.find((item) => item.id === id)
    if (!team) {
      throw new Error('Team not found')
    }
    return {
      team_id: id,
      status: team.status,
      waiting: team.assignments.filter((item) => item.status === 'waiting').map((item) => item.id),
      running: team.assignments.filter((item) => item.status === 'running').map((item) => item.id),
      completed: team.assignments.filter((item) => item.status === 'completed').map((item) => item.id),
      failed: team.assignments.filter((item) => item.status === 'failed').map((item) => item.id),
    }
  }

  async getProjectGraph(id: string): Promise<ProjectGraphPayload> {
    if (!this.knowledgeGraphs[id]) {
      const project = mockProjects.find((item) => item.id === id)
      const projectNode: KnowledgeNode = {
        id,
        node_type: 'Project',
        label: project?.name ?? id,
        project_id: id,
        workspace_id: project?.workspaceId ?? null,
        source_id: id,
        metadata: {},
        archived: false,
        created_at: new Date().toISOString(),
      }
      const assetNodes: KnowledgeNode[] = this.assets
        .filter((asset) => asset.projectId === id)
        .map((asset) => ({
          id: asset.id,
          node_type: asset.type,
          label: asset.title,
          project_id: id,
          workspace_id: project?.workspaceId ?? null,
          source_id: asset.id,
          metadata: asset.metadata ?? {},
          archived: false,
          created_at: asset.createdAt ?? new Date().toISOString(),
        }))
      const nodes = [projectNode, ...assetNodes]
      const edges = assetNodes.map((asset) => ({
        id: `edge-${asset.id}`,
        relationship: 'belongs_to',
        from_node: asset.id,
        to_node: id,
        metadata: {},
        created_at: new Date().toISOString(),
      }))
      this.knowledgeGraphs[id] = {
        graph: { nodes, edges },
        snapshot: {
          id: `snapshot-${Date.now()}`,
          scope_type: 'project',
          scope_id: id,
          node_ids: nodes.map((node) => node.id),
          edge_ids: edges.map((edge) => edge.id),
          created_at: new Date().toISOString(),
        },
      }
    }
    return this.knowledgeGraphs[id]
  }

  async getGraphNode(id: string): Promise<KnowledgeNode | undefined> {
    const graphs = await Promise.all(mockProjects.map((project) => this.getProjectGraph(project.id)))
    return graphs.flatMap((graph) => graph.graph.nodes).find((node) => node.id === id)
  }

  async getGraphNeighbors(id: string): Promise<KnowledgeNode[]> {
    const graphs = await Promise.all(mockProjects.map((project) => this.getProjectGraph(project.id)))
    const nodes = graphs.flatMap((graph) => graph.graph.nodes)
    const edges = graphs.flatMap((graph) => graph.graph.edges)
    const neighborIds = edges.filter((edge) => edge.from_node === id || edge.to_node === id).flatMap((edge) => [edge.from_node, edge.to_node]).filter((nodeId) => nodeId !== id)
    return nodes.filter((node) => neighborIds.includes(node.id))
  }

  async getGraphPath(start: string, end: string): Promise<{ path: string[] }> {
    if (start === end) {
      return { path: [start] }
    }
    return { path: [start, end] }
  }

  async getGraphContext(projectId: string): Promise<ContextBundle> {
    const graph = await this.getProjectGraph(projectId)
    return {
      project: mockProjects.find((project) => project.id === projectId) ?? {},
      recent_chats: this.conversations.filter((item) => item.project_id === projectId),
      related_assets: this.assets.filter((item) => item.projectId === projectId),
      research_findings: this.researchSessions.filter((item) => item.project_id === projectId),
      reviews: this.reviews.filter((item) => item.project_id === projectId),
      agent_history: this.agents.filter((item) => item.project_id === projectId),
      workflow_history: this.workflows.filter((item) => item.project_id === projectId),
      execution_history: this.runtimeExecutions,
      referenced_images: this.assets.filter((item) => item.projectId === projectId && item.type === 'Image'),
      referenced_reports: this.assets.filter((item) => item.projectId === projectId && item.type === 'Document'),
      graph: graph.graph,
    }
  }

  async getGraphLineage(assetId: string): Promise<KnowledgeGraph> {
    const asset = this.assets.find((item) => item.id === assetId)
    if (!asset) {
      return { nodes: [], edges: [] }
    }
    const graph = await this.getProjectGraph(asset.projectId)
    return {
      nodes: graph.graph.nodes.filter((node) => node.id === assetId || node.id === asset.metadata?.parent_asset_id),
      edges: graph.graph.edges.filter((edge) => edge.from_node === assetId || edge.to_node === assetId),
    }
  }

  async getGraphHistory(nodeId: string): Promise<Array<Record<string, unknown>>> {
    const node = await this.getGraphNode(nodeId)
    if (!node) {
      return []
    }
    return [{ type: 'node_created', node_id: nodeId, timestamp: node.created_at }]
  }

  async listAutomationRules(projectId?: string): Promise<AutomationRule[]> {
    const rules = [...this.automationRules.values()]
    const scoped = projectId ? rules.filter((rule) => rule.project_id === projectId) : rules
    return scoped.sort((a, b) => b.priority - a.priority || a.created_at.localeCompare(b.created_at))
  }

  async getAutomationRule(id: string): Promise<AutomationRule | undefined> {
    return this.automationRules.get(id)
  }

  async createAutomationRule(request: AutomationRuleRequest): Promise<AutomationRule> {
    const now = new Date().toISOString()
    const rule: AutomationRule = {
      id: `automation-${this.automationRules.size + 1}`,
      project_id: request.projectId ?? null,
      workspace_id: request.workspaceId ?? null,
      name: request.name,
      description: request.description ?? '',
      trigger: request.trigger,
      conditions: request.conditions ?? [],
      actions: request.actions ?? [],
      schedule: request.schedule ?? null,
      priority: request.priority ?? 0,
      enabled: true,
      dry_run: request.dryRun ?? false,
      created_at: now,
      updated_at: now,
      disabled_at: null,
    }
    this.automationRules.set(rule.id, rule)
    return rule
  }

  async updateAutomationRule(id: string, request: AutomationRuleUpdateRequest): Promise<AutomationRule> {
    const existing = this.automationRules.get(id)
    if (!existing) {
      throw new Error('Automation rule not found')
    }
    const updated: AutomationRule = {
      ...existing,
      name: request.name ?? existing.name,
      description: request.description ?? existing.description,
      trigger: request.trigger ?? existing.trigger,
      conditions: request.conditions ?? existing.conditions,
      actions: request.actions ?? existing.actions,
      schedule: request.schedule ?? existing.schedule,
      priority: request.priority ?? existing.priority,
      dry_run: request.dryRun ?? existing.dry_run,
      updated_at: new Date().toISOString(),
    }
    this.automationRules.set(id, updated)
    return updated
  }

  async deleteAutomationRule(id: string): Promise<void> {
    this.automationRules.delete(id)
  }

  async enableAutomationRule(id: string): Promise<AutomationRule> {
    return this.setAutomationEnabled(id, true)
  }

  async disableAutomationRule(id: string): Promise<AutomationRule> {
    return this.setAutomationEnabled(id, false)
  }

  async runAutomationRule(id: string, request?: AutomationRunRequest): Promise<AutomationRun> {
    return this.recordAutomationRun(id, request, false)
  }

  async dryRunAutomationRule(id: string, request?: AutomationRunRequest): Promise<AutomationRun> {
    return this.recordAutomationRun(id, request, true)
  }

  async getAutomationHistory(id: string): Promise<AutomationRun[]> {
    return this.listAutomationRuns(id)
  }

  async getAutomationState(id: string): Promise<AutomationState> {
    const rule = this.automationRules.get(id)
    const runs = await this.listAutomationRuns(id)
    const latest = runs[0]
    return {
      rule_id: id,
      enabled: rule?.enabled ?? false,
      last_run_id: latest?.id ?? null,
      last_status: latest?.status ?? null,
      last_run_at: latest?.start_time ?? null,
      next_run_at: null,
      total_runs: runs.length,
      failure_count: runs.filter((run) => run.status === 'failed').length,
    }
  }

  async listAutomationRuns(ruleId?: string): Promise<AutomationRun[]> {
    const runs = ruleId
      ? this.automationRuns.filter((run) => run.rule_id === ruleId)
      : [...this.automationRuns]
    return runs.sort((a, b) => b.start_time.localeCompare(a.start_time))
  }

  async listAutomationLogs(params?: { runId?: string; ruleId?: string }): Promise<AutomationLog[]> {
    return this.automationLogs.filter(
      (log) =>
        (!params?.runId || log.run_id === params.runId) &&
        (!params?.ruleId || log.rule_id === params.ruleId),
    )
  }

  async listAutomationConflicts(projectId?: string): Promise<AutomationConflict[]> {
    const rules = (await this.listAutomationRules(projectId)).filter((rule) => rule.enabled)
    const buckets = new Map<string, string[]>()
    for (const rule of rules) {
      const key = `${rule.trigger.type}|${rule.priority}`
      buckets.set(key, [...(buckets.get(key) ?? []), rule.id])
    }
    return [...buckets.entries()]
      .filter(([, ids]) => ids.length > 1)
      .map(([key, ids]) => ({
        trigger: key.split('|')[0],
        priority: Number(key.split('|')[1]),
        rule_ids: ids,
      }))
  }

  private setAutomationEnabled(id: string, enabled: boolean): AutomationRule {
    const existing = this.automationRules.get(id)
    if (!existing) {
      throw new Error('Automation rule not found')
    }
    const now = new Date().toISOString()
    const updated: AutomationRule = {
      ...existing,
      enabled,
      disabled_at: enabled ? null : now,
      updated_at: now,
    }
    this.automationRules.set(id, updated)
    return updated
  }

  private recordAutomationRun(
    id: string,
    request: AutomationRunRequest | undefined,
    dryRun: boolean,
  ): AutomationRun {
    const rule = this.automationRules.get(id)
    if (!rule) {
      throw new Error('Automation rule not found')
    }
    const start = new Date().toISOString()
    const run: AutomationRun = {
      id: `automation-run-${this.automationRuns.length + 1}`,
      rule_id: id,
      triggered_by: rule.trigger.type,
      status: rule.enabled ? 'completed' : 'skipped',
      start_time: start,
      end_time: start,
      duration_ms: 12,
      trigger_data: request?.triggerData ?? {},
      outputs: rule.enabled
        ? { dry_run: dryRun, state_actions: rule.actions.map((action) => ({ type: action.type, applied: !dryRun })) }
        : { skip_reason: 'rule disabled' },
      error: null,
      retries: 0,
      created_at: start,
    }
    this.automationRuns.push(run)
    this.automationLogs.push({
      id: `automation-log-${this.automationLogs.length + 1}`,
      run_id: run.id,
      rule_id: id,
      level: 'info',
      message: dryRun ? '[dry-run] evaluated rule' : 'evaluated rule',
      actor: request?.actor ?? 'system',
      context: {},
      created_at: start,
    })
    return run
  }

  async listApprovals(params?: { pendingOnly?: boolean; projectId?: string }): Promise<ApprovalRequest[]> {
    let approvals = [...this.approvals.values()]
    if (params?.pendingOnly) approvals = approvals.filter((a) => a.state === 'pending')
    if (params?.projectId) approvals = approvals.filter((a) => a.project_id === params.projectId)
    return approvals.sort((a, b) => b.priority - a.priority || a.created_at.localeCompare(b.created_at))
  }

  async getApproval(id: string): Promise<ApprovalRequest | undefined> {
    return this.approvals.get(id)
  }

  async createApproval(payload: ApprovalCreatePayload): Promise<ApprovalRequest> {
    const now = new Date().toISOString()
    const approval: ApprovalRequest = {
      id: `approval-${this.approvals.size + 1}`,
      title: payload.title,
      state: 'pending',
      action: payload.action ?? '',
      scopes: payload.scopes ?? [],
      estimated_cost: payload.estimatedCost ?? 0,
      reason: 'Mock policy requires approval',
      policy_id: null,
      policy_name: 'mock-policy',
      required_approvers: [],
      approvals_required: 1,
      decisions: [],
      viewed_by: [],
      priority: payload.priority ?? 0,
      project_id: payload.projectId ?? null,
      workspace_id: payload.workspaceId ?? null,
      agent_id: payload.agentId ?? null,
      execution_id: payload.executionId ?? null,
      schedule_id: payload.scheduleId ?? null,
      entry_id: payload.entryId ?? null,
      run_id: null,
      job_id: null,
      asset_id: null,
      payload: payload.payload ?? {},
      metadata: payload.metadata ?? {},
      requested_by: payload.requestedBy ?? 'system',
      created_at: now,
      updated_at: now,
      expires_at: null,
      decided_at: null,
    }
    this.approvals.set(approval.id, approval)
    this.recordApprovalHistory(approval.id, 'created', approval.requested_by, null, 'pending')
    return approval
  }

  async approveApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest> {
    return this.decideApproval(id, payload, 'approve', 'approved')
  }

  async rejectApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest> {
    return this.decideApproval(id, payload, 'reject', 'rejected')
  }

  async requestChangesApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest> {
    return this.decideApproval(id, payload, 'request_changes', 'pending')
  }

  async cancelApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest> {
    return this.decideApproval(id, payload, 'reject', 'cancelled')
  }

  async viewApproval(id: string, actor: string): Promise<ApprovalRequest> {
    const approval = this.requireApproval(id)
    if (!approval.viewed_by.includes(actor)) {
      approval.viewed_by = [...approval.viewed_by, actor]
      approval.updated_at = new Date().toISOString()
      this.approvals.set(id, approval)
      this.recordApprovalHistory(id, 'viewed', actor, null, null)
    }
    return approval
  }

  async escalateApproval(id: string, actor: string, escalatedTo: string): Promise<ApprovalRequest> {
    const approval = this.requireApproval(id)
    if (!approval.required_approvers.includes(escalatedTo)) {
      approval.required_approvers = [...approval.required_approvers, escalatedTo]
    }
    approval.updated_at = new Date().toISOString()
    this.approvals.set(id, approval)
    this.recordApprovalHistory(id, 'escalated', actor, null, null)
    return approval
  }

  async resumeApprovedExecution(id: string): Promise<RuntimeExecutionRecord> {
    const approval = this.requireApproval(id)
    const execution = this.runtimeExecutions.find((e) => e.execution_id === approval.execution_id)
    if (!execution) {
      throw new Error('Approval has no linked execution')
    }
    return execution
  }

  async getApprovalHistory(approvalId?: string): Promise<ApprovalHistoryEvent[]> {
    const events = approvalId
      ? this.approvalHistory.filter((e) => e.approval_id === approvalId)
      : [...this.approvalHistory]
    return events.sort((a, b) => b.created_at.localeCompare(a.created_at))
  }

  async listApprovalPolicies(projectId?: string): Promise<ApprovalPolicy[]> {
    const policies = [...this.approvalPolicies.values()]
    return projectId ? policies.filter((p) => !p.project_id || p.project_id === projectId) : policies
  }

  async upsertApprovalPolicy(policy: Partial<ApprovalPolicy> & { name: string }): Promise<ApprovalPolicy> {
    const now = new Date().toISOString()
    const id = policy.id ?? `approval-policy-${this.approvalPolicies.size + 1}`
    const stored: ApprovalPolicy = {
      id,
      name: policy.name,
      description: policy.description ?? '',
      mode: policy.mode ?? 'scoped',
      scopes: policy.scopes ?? [],
      cost_threshold: policy.cost_threshold ?? null,
      conditions: policy.conditions ?? [],
      required_approvers: policy.required_approvers ?? [],
      approvals_required: policy.approvals_required ?? 1,
      expires_after_seconds: policy.expires_after_seconds ?? null,
      project_id: policy.project_id ?? null,
      workspace_id: policy.workspace_id ?? null,
      priority: policy.priority ?? 0,
      enabled: policy.enabled ?? true,
      metadata: policy.metadata ?? {},
      created_at: this.approvalPolicies.get(id)?.created_at ?? now,
      updated_at: now,
    }
    this.approvalPolicies.set(id, stored)
    return stored
  }

  async listExecutionsWaitingApproval(): Promise<RuntimeExecutionRecord[]> {
    return this.runtimeExecutions.filter((e) => e.status === 'waiting_approval')
  }

  private requireApproval(id: string): ApprovalRequest {
    const approval = this.approvals.get(id)
    if (!approval) {
      throw new Error('Approval request not found')
    }
    return approval
  }

  private decideApproval(
    id: string,
    payload: ApprovalDecisionPayload,
    decision: 'approve' | 'reject' | 'request_changes',
    nextState: ApprovalState,
  ): ApprovalRequest {
    const approval = this.requireApproval(id)
    if (approval.state !== 'pending') {
      throw new Error(`Approval is already ${approval.state}`)
    }
    if (payload.actor === approval.requested_by) {
      throw new Error('Requester may not decide their own approval')
    }
    const now = new Date().toISOString()
    approval.decisions = [
      ...approval.decisions,
      {
        id: `decision-${approval.decisions.length + 1}`,
        decision,
        actor: payload.actor,
        comment: payload.comment ?? null,
        metadata: {},
        created_at: now,
      },
    ]
    approval.state = nextState
    approval.updated_at = now
    if (nextState !== 'pending') {
      approval.decided_at = now
    }
    this.approvals.set(id, approval)
    this.recordApprovalHistory(id, decision, payload.actor, 'pending', nextState)
    return approval
  }

  private recordApprovalHistory(
    approvalId: string,
    eventType: string,
    actor: string,
    fromState: ApprovalState | null,
    toState: ApprovalState | null,
  ): void {
    this.approvalHistory.push({
      id: `approval-history-${this.approvalHistory.length + 1}`,
      approval_id: approvalId,
      event_type: eventType,
      actor,
      comment: null,
      from_state: fromState,
      to_state: toState,
      metadata: {},
      created_at: new Date().toISOString(),
    })
  }
}

export const mockProvider = new MockProvider()

function normalizeAssetType(assetType: string | undefined, mimeType: string, fileName: string): 'Image' | 'Document' | 'Code' | 'Text' | 'Video' | 'Dataset' | 'Workflow' {
  if (assetType) {
    const normalized = assetType.toLowerCase()
    if (normalized === 'image') return 'Image'
    if (normalized === 'document') return 'Document'
    if (normalized === 'code') return 'Code'
    if (normalized === 'text') return 'Text'
  }
  if (mimeType.startsWith('image/')) return 'Image'
  if (fileName.endsWith('.py') || fileName.endsWith('.ts') || fileName.endsWith('.tsx') || fileName.endsWith('.js')) return 'Code'
  if (fileName.endsWith('.txt') || fileName.endsWith('.md')) return 'Text'
  return 'Document'
}
