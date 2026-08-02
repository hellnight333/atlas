import { AtlasApiClient } from '../api/client'
import { atlasEndpoints } from '../api/endpoints'
import type {
  Agent,
  AgentMessage,
  AgentCreateRequest,
  AgentMemoryAttachRequest,
  AgentMemoryReference,
  AgentPlanRequest,
  ExecutionSchedule,
  RuntimeExecutionRecord,
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
  AtlasProvider,
  Capability,
  ContextBundle,
  KnowledgeGraph,
  KnowledgeNode,
  ProjectGraphPayload,
  ResearchGraph,
  ResearchReportRequest,
  ResearchSearchRequest,
  ResearchSession,
  ResearchSessionRequest,
  ResearchSummarizeRequest,
  ImageAsset,
  ImageGenerateRequest,
  ImageGenerationResult,
  ImageVariantRequest,
  ReviewComment,
  ReviewCommentRequest,
  ReviewDecisionRequest,
  ReviewHistoryEvent,
  ReviewPublishRequest,
  ReviewSession,
  ReviewSessionRequest,
  SearchResult,
  PlannerExecutionPlan,
  QueueUpdateResult,
  ScheduleQueueEntry,
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
import type {
  AgentTask,
  Asset,
  CommandItem,
  Job,
  NotificationItem,
  Project,
  Studio,
} from '../types/domain'

export class KernelProvider implements AtlasProvider {
  readonly mode = 'kernel-local' as const
  private readonly client: AtlasApiClient

  constructor(client: AtlasApiClient) {
    this.client = client
  }

  async getProjects(): Promise<Project[]> {
    const projects = await this.client.get<Array<Record<string, unknown>>>(atlasEndpoints.projects)
    return projects.map(mapProject)
  }

  async getProject(id: string): Promise<Project | undefined> {
    const project = await this.client.get<Record<string, unknown>>(atlasEndpoints.project(id))
    return mapProject(project)
  }

  async getAssets(): Promise<Asset[]> {
    const assets = await this.client.get<Array<Record<string, unknown>>>(atlasEndpoints.assets)
    return assets.map(mapAsset)
  }

  async getProjectAssets(projectId: string): Promise<Asset[]> {
    const assets = await this.client.get<Array<Record<string, unknown>>>(atlasEndpoints.projectAssets(projectId))
    return assets.map(mapAsset)
  }

  async getAsset(id: string): Promise<Asset | undefined> {
    const asset = await this.client.get<Record<string, unknown>>(atlasEndpoints.asset(id))
    return mapAsset(asset)
  }

  async importAsset(request: AssetImportRequest): Promise<Asset> {
    const form = new FormData()
    form.append('file', request.file)
    form.append('project_id', request.projectId)
    if (request.workflowId) form.append('workflow_id', request.workflowId)
    if (request.runId) form.append('run_id', request.runId)
    if (request.jobId) form.append('job_id', request.jobId)
    if (request.assetType) form.append('asset_type', request.assetType)
    form.append('tags', JSON.stringify(request.tags ?? []))
    const asset = await this.client.post<Record<string, unknown>>(atlasEndpoints.assetImport, form)
    return mapAsset(asset)
  }

  async deleteAsset(id: string): Promise<void> {
    await this.client.delete(atlasEndpoints.asset(id))
  }

  async getRuns(): Promise<Job[]> {
    const jobs = await this.client.get<Array<Record<string, unknown>>>(atlasEndpoints.runs)
    return jobs.map(mapJob)
  }

  async getActivities(): Promise<Job[]> {
    const activities = await this.client.get<Array<Record<string, unknown>>>(atlasEndpoints.activities)
    return activities.map(mapJob)
  }

  async getAgentTasks(): Promise<AgentTask[]> {
    const agentTasks = await this.client.get<Array<Record<string, unknown>>>(`${atlasEndpoints.activities}?domain=agent`)
    return agentTasks.map(mapAgentTask)
  }

  async getNotifications(): Promise<NotificationItem[]> {
    return this.client.get(atlasEndpoints.notifications)
  }

  async getCapabilities(): Promise<Capability[]> {
    return this.client.get(atlasEndpoints.capabilities)
  }

  async getStudios(): Promise<Studio[]> {
    return this.client.get(atlasEndpoints.studios)
  }

  async getCommands(): Promise<CommandItem[]> {
    return this.client.get(atlasEndpoints.commands)
  }

  async getWorkflows(): Promise<WorkflowDefinitionPayload[]> {
    return this.client.get(atlasEndpoints.workflows)
  }

  async getWorkflow(id: string): Promise<WorkflowDefinitionPayload | undefined> {
    return this.client.get(atlasEndpoints.workflow(id))
  }

  async createWorkflow(definition: WorkflowDefinitionPayload): Promise<WorkflowDefinitionPayload> {
    return this.client.post(atlasEndpoints.workflows, definition)
  }

  async executeWorkflowDefinition(id: string): Promise<WorkflowExecutionPayload> {
    return this.client.post(atlasEndpoints.workflowExecute(id), {})
  }

  async getExecution(id: string): Promise<WorkflowExecutionPayload | undefined> {
    return this.client.get(atlasEndpoints.execution(id))
  }

  async getExecutionTimeline(id: string): Promise<Array<Record<string, unknown>>> {
    return this.client.get(atlasEndpoints.executionTimeline(id))
  }

  async search(query: string): Promise<SearchResult[]> {
    return this.client.get(`${atlasEndpoints.search}?q=${encodeURIComponent(query)}`)
  }

  async executeWorkflow(request: WorkflowExecutionRequest): Promise<WorkflowExecutionResult> {
    return this.client.post(atlasEndpoints.executeWorkflow, request)
  }

  async createChatConversation(request: ChatConversationRequest): Promise<ChatConversation> {
    return this.client.post(atlasEndpoints.chatConversations, request)
  }

  async listChatConversations(projectId?: string): Promise<ChatConversation[]> {
    const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    return this.client.get(`${atlasEndpoints.chatConversations}${suffix}`)
  }

  async getChatConversation(id: string): Promise<ChatConversation | undefined> {
    return this.client.get(atlasEndpoints.chatConversation(id))
  }

  async sendChatMessage(request: ChatMessageRequest): Promise<ChatMessage> {
    return this.client.post(atlasEndpoints.chatMessage, request)
  }

  async updateChatConversation(id: string, request: ChatConversationUpdateRequest): Promise<ChatConversation> {
    return this.client.post(atlasEndpoints.chatConversation(id), request)
  }

  async deleteChatConversation(id: string): Promise<void> {
    await this.client.delete(atlasEndpoints.chatConversation(id))
  }

  async createResearchSession(request: ResearchSessionRequest): Promise<ResearchSession> {
    return this.client.post(atlasEndpoints.researchSession, {
      project_id: request.projectId,
      title: request.title,
      question: request.question,
      conversation_id: request.conversationId,
      metadata: request.metadata,
    })
  }

  async listResearchSessions(projectId?: string): Promise<ResearchSession[]> {
    const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    return this.client.get(`${atlasEndpoints.researchSession}${suffix}`)
  }

  async getResearchSession(id: string): Promise<ResearchSession | undefined> {
    return this.client.get(atlasEndpoints.researchSessionById(id))
  }

  async searchResearch(request: ResearchSearchRequest): Promise<{ session_id: string; provider: string; sources: Array<Record<string, unknown>> }> {
    return this.client.post(atlasEndpoints.researchSearch, {
      session_id: request.sessionId,
      query: request.query,
      provider: request.provider,
    })
  }

  async summarizeResearch(request: ResearchSummarizeRequest): Promise<{ run_id: string; job_id: string; provider: string; asset: Record<string, unknown> }> {
    return this.client.post(atlasEndpoints.researchSummarize, {
      session_id: request.sessionId,
      source_asset_ids: request.sourceAssetIds,
      prompt: request.prompt,
    })
  }

  async generateResearchReport(request: ResearchReportRequest): Promise<Record<string, unknown>> {
    return this.client.post(atlasEndpoints.researchReport, {
      session_id: request.sessionId,
      format: request.format,
      prompt: request.prompt,
    })
  }

  async getResearchGraph(projectId: string): Promise<ResearchGraph> {
    return this.client.get(atlasEndpoints.researchGraph(projectId))
  }

  async createReviewSession(request: ReviewSessionRequest): Promise<ReviewSession> {
    return this.client.post(atlasEndpoints.reviews, {
      project_id: request.projectId,
      title: request.title,
      asset_id: request.assetId,
      workflow_id: request.workflowId,
      metadata: request.metadata,
    })
  }

  async listReviewSessions(projectId?: string): Promise<ReviewSession[]> {
    const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    return this.client.get(`${atlasEndpoints.reviews}${suffix}`)
  }

  async approveReview(id: string, request: ReviewDecisionRequest): Promise<ReviewSession> {
    return this.client.post(atlasEndpoints.reviewApprove(id), {
      asset_id: request.assetId,
      comment: request.comment,
      metadata: request.metadata,
    })
  }

  async rejectReview(id: string, request: ReviewDecisionRequest): Promise<ReviewSession> {
    return this.client.post(atlasEndpoints.reviewReject(id), {
      asset_id: request.assetId,
      comment: request.comment,
      metadata: request.metadata,
    })
  }

  async commentReview(id: string, request: ReviewCommentRequest): Promise<ReviewComment> {
    return this.client.post(atlasEndpoints.reviewComment(id), {
      content: request.content,
      metadata: request.metadata,
    })
  }

  async publishReview(id: string, request: ReviewPublishRequest): Promise<Record<string, unknown>> {
    return this.client.post(atlasEndpoints.reviewPublish(id), {
      asset_id: request.assetId,
      metadata: request.metadata,
    })
  }

  async getReviewHistory(id: string): Promise<ReviewHistoryEvent[]> {
    return this.client.get(atlasEndpoints.reviewHistory(id))
  }

    async generateImage(request: ImageGenerateRequest): Promise<ImageGenerationResult> {
      return this.client.post(atlasEndpoints.imagesGenerate, {
        project_id: request.projectId,
        prompt: request.prompt,
        negative_prompt: request.negativePrompt,
        styles: request.styles,
        template: request.template,
        variables: request.variables,
        seed: request.seed,
        steps: request.steps,
        cfg: request.cfg,
        resolution: request.resolution,
        sampler: request.sampler,
        provider: request.provider,
        workflow: request.workflow,
        model: request.model,
        metadata: request.metadata,
      })
    }

    async listImages(projectId?: string): Promise<ImageAsset[]> {
      const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
      return this.client.get(`${atlasEndpoints.images}${suffix}`)
    }

    async getImage(id: string): Promise<ImageAsset | undefined> {
      return this.client.get(atlasEndpoints.image(id))
    }

    async createImageVariant(id: string, request: ImageVariantRequest): Promise<ImageGenerationResult> {
      return this.client.post(atlasEndpoints.imageVariant(id), {
        prompt: request.prompt,
        negative_prompt: request.negativePrompt,
        styles: request.styles,
        template: request.template,
        variables: request.variables,
        seed: request.seed,
        steps: request.steps,
        cfg: request.cfg,
        resolution: request.resolution,
        sampler: request.sampler,
        provider: request.provider,
        workflow: request.workflow,
        model: request.model,
        metadata: request.metadata,
      })
    }

    async regenerateImage(id: string, request: ImageVariantRequest): Promise<ImageGenerationResult> {
      return this.client.post(atlasEndpoints.imageRegenerate(id), {
        prompt: request.prompt,
        negative_prompt: request.negativePrompt,
        styles: request.styles,
        template: request.template,
        variables: request.variables,
        seed: request.seed,
        steps: request.steps,
        cfg: request.cfg,
        resolution: request.resolution,
        sampler: request.sampler,
        provider: request.provider,
        workflow: request.workflow,
        model: request.model,
        metadata: request.metadata,
      })
    }

    async getImageVersions(id: string): Promise<ImageAsset[]> {
      return this.client.get(atlasEndpoints.imageVersions(id))
    }

    async getWorkspaceContext(projectId: string): Promise<WorkspaceContextPayload> {
      return this.client.get(atlasEndpoints.workspaceContext(projectId))
    }

    async getWorkspaceRecommendations(projectId: string): Promise<WorkspaceRecommendationsPayload> {
      return this.client.get(atlasEndpoints.workspaceRecommendations(projectId))
    }

    async getWorkspaceRecent(projectId: string): Promise<WorkspaceRecentPayload> {
      return this.client.get(atlasEndpoints.workspaceRecent(projectId))
    }

    async getWorkspaceDashboard(projectId: string): Promise<WorkspaceDashboardPayload> {
      return this.client.get(atlasEndpoints.workspaceDashboard(projectId))
    }

    async listAgents(projectId?: string): Promise<Agent[]> {
      const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
      return this.client.get(`${atlasEndpoints.agents}${suffix}`)
    }

    async getAgent(id: string): Promise<Agent | undefined> {
      return this.client.get(atlasEndpoints.agent(id))
    }

    async createAgent(request: AgentCreateRequest): Promise<Agent> {
      return this.client.post(atlasEndpoints.agents, {
        name: request.name,
        description: request.description,
        role: request.role,
        workspace_id: request.workspaceId,
        project_id: request.projectId,
        capabilities: request.capabilities,
        status: request.status,
        memory_id: request.memoryId,
        permission_set: request.permissionSet,
      })
    }

    async updateAgent(id: string, request: AgentUpdateRequest): Promise<Agent> {
      return this.client.patch(atlasEndpoints.agent(id), {
        name: request.name,
        description: request.description,
        role: request.role,
        workspace_id: request.workspaceId,
        project_id: request.projectId,
        capabilities: request.capabilities,
        status: request.status,
        memory_id: request.memoryId,
        permission_set: request.permissionSet,
      })
    }

    async deleteAgent(id: string): Promise<void> {
      await this.client.delete(atlasEndpoints.agent(id))
    }

    async listAgentMemory(id: string): Promise<AgentMemoryReference[]> {
      return this.client.get(atlasEndpoints.agentMemory(id))
    }

    async attachAgentMemory(id: string, request: AgentMemoryAttachRequest): Promise<AgentMemoryReference> {
      return this.client.post(atlasEndpoints.agentMemory(id), {
        kind: request.kind,
        asset_id: request.assetId,
      })
    }

    async getAgentPermissions(id: string): Promise<AgentPermission[]> {
      return this.client.get(atlasEndpoints.agentPermissions(id))
    }

    async generateAgentPlan(id: string, request: AgentPlanRequest): Promise<PlannerExecutionPlan> {
      return this.client.post(atlasEndpoints.agentPlan(id), {
        goal: request.goal,
      })
    }

    async createSchedule(request: SchedulerCreateRequest): Promise<ExecutionSchedule> {
      return this.client.post(atlasEndpoints.schedulerSchedule, {
        agent_id: request.agentId,
        goal: request.goal,
        priority: request.priority,
        available_executors: request.availableExecutors,
        execution_policy: request.executionPolicy,
      })
    }

    async getSchedule(id: string): Promise<ExecutionSchedule> {
      return this.client.get(atlasEndpoints.schedulerById(id))
    }

    async getScheduleQueue(id: string): Promise<ScheduleQueueEntry[]> {
      return this.client.get(atlasEndpoints.schedulerQueue(id))
    }

    async pauseSchedule(id: string): Promise<QueueUpdateResult> {
      return this.client.post(atlasEndpoints.schedulerPause(id), {})
    }

    async resumeSchedule(id: string): Promise<QueueUpdateResult> {
      return this.client.post(atlasEndpoints.schedulerResume(id), {})
    }

    async cancelSchedule(id: string): Promise<QueueUpdateResult> {
      return this.client.post(atlasEndpoints.schedulerCancel(id), {})
    }

    async startRuntimeSchedule(id: string): Promise<RuntimeExecutionRecord[]> {
      return this.client.post(atlasEndpoints.runtimeStartSchedule(id), {})
    }

    async listRuntime(): Promise<RuntimeExecutionRecord[]> {
      return this.client.get(atlasEndpoints.runtime)
    }

    async listRuntimeRunning(): Promise<RuntimeExecutionRecord[]> {
      return this.client.get(atlasEndpoints.runtimeRunning)
    }

    async listRuntimeHistory(): Promise<RuntimeExecutionRecord[]> {
      return this.client.get(atlasEndpoints.runtimeHistory)
    }

    async getRuntimeExecution(id: string): Promise<RuntimeExecutionRecord | undefined> {
      return this.client.get(atlasEndpoints.runtimeById(id))
    }

    async cancelRuntimeExecution(id: string): Promise<RuntimeExecutionRecord> {
      return this.client.post(atlasEndpoints.runtimeCancel(id), {})
    }

    async retryRuntimeExecution(id: string): Promise<RuntimeExecutionRecord> {
      return this.client.post(atlasEndpoints.runtimeRetry(id), {})
    }

    async createAgentTeam(request: AgentTeamCreateRequest): Promise<AgentTeam> {
      return this.client.post(atlasEndpoints.agentTeam, {
        name: request.name,
        project_id: request.projectId,
        workspace_id: request.workspaceId,
        assignments: request.assignments.map((assignment) => ({
          agent_id: assignment.agentId,
          role: assignment.role,
          title: assignment.title,
          action: assignment.action,
          payload: assignment.payload ?? {},
          dependencies: assignment.dependencies ?? [],
        })),
      })
    }

    async getAgentTeam(id: string): Promise<AgentTeam | undefined> {
      return this.client.get(atlasEndpoints.agentTeamById(id))
    }

    async getAgentTeamMessages(id: string): Promise<AgentMessage[]> {
      return this.client.get(atlasEndpoints.agentTeamMessages(id))
    }

    async cancelAgentTeam(id: string): Promise<AgentTeam> {
      return this.client.post(atlasEndpoints.agentTeamCancel(id), {})
    }

    async getAgentTeamStatus(id: string): Promise<AgentTeamStatusPayload> {
      return this.client.get(atlasEndpoints.agentTeamStatus(id))
    }

    async getProjectGraph(id: string): Promise<ProjectGraphPayload> {
      return this.client.get(atlasEndpoints.graphProject(id))
    }

    async getGraphNode(id: string): Promise<KnowledgeNode | undefined> {
      return this.client.get(atlasEndpoints.graphNode(id))
    }

    async getGraphNeighbors(id: string): Promise<KnowledgeNode[]> {
      return this.client.get(atlasEndpoints.graphNeighbors(id))
    }

    async getGraphPath(start: string, end: string): Promise<{ path: string[] }> {
      return this.client.get(`${atlasEndpoints.graphPath}?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`)
    }

    async getGraphContext(projectId: string): Promise<ContextBundle> {
      return this.client.get(atlasEndpoints.graphContext(projectId))
    }

    async getGraphLineage(assetId: string): Promise<KnowledgeGraph> {
      return this.client.get(atlasEndpoints.graphLineage(assetId))
    }

    async getGraphHistory(nodeId: string): Promise<Array<Record<string, unknown>>> {
      return this.client.get(atlasEndpoints.graphHistory(nodeId))
    }
}

export const kernelProvider = new KernelProvider(new AtlasApiClient())

function mapProject(payload: Record<string, unknown>): Project {
  return {
    id: String(payload.id),
    name: String(payload.name),
    studio: 'Research Studio',
    status: 'active',
    progress: 100,
    description: typeof payload.description === 'string' ? payload.description : undefined,
    workspaceId: typeof payload.workspace_id === 'string' ? payload.workspace_id : null,
  }
}

function mapAsset(payload: Record<string, unknown>): Asset {
  return {
    id: String(payload.id),
    title: String((payload.metadata as Record<string, unknown> | undefined)?.original_filename ?? payload.id),
    type: mapAssetType(String(payload.type ?? 'document')),
    projectId: String(payload.project_id ?? 'project-unassigned'),
    freshness: 'authoritative_live',
    version: Number(payload.version ?? 1),
    uri: String(payload.uri ?? ''),
    mimeType: typeof payload.mime_type === 'string' ? payload.mime_type : null,
    fileSize: typeof payload.file_size === 'number' ? payload.file_size : null,
    contentHash: typeof payload.content_hash === 'string' ? payload.content_hash : null,
    createdAt: typeof payload.created_at === 'string' ? payload.created_at : undefined,
    updatedAt: typeof payload.updated_at === 'string' ? payload.updated_at : undefined,
    metadata: typeof payload.metadata === 'object' && payload.metadata !== null ? (payload.metadata as Record<string, unknown>) : {},
    tags: Array.isArray(payload.tags) ? payload.tags.map(String) : [],
  }
}

function mapJob(payload: Record<string, unknown>): Job {
  return {
    id: String(payload.id),
    name: String(payload.name ?? payload.title ?? payload.action ?? payload.id),
    projectId: String(payload.projectId ?? payload.project_id ?? 'project-unassigned'),
    domain: (String(payload.domain ?? 'uploads') as Job['domain']),
    state: (String(payload.state ?? payload.status ?? 'queued') as Job['state']),
    severity: (String(payload.severity ?? 'info') as Job['severity']),
    progress: Number(payload.progress ?? 0),
    elapsed: String(payload.elapsed ?? 'unknown'),
  }
}

function mapAgentTask(payload: Record<string, unknown>): AgentTask {
  return {
    id: String(payload.id),
    name: String(payload.name),
    projectId: String(payload.projectId ?? 'project-unassigned'),
    status: (String(payload.status ?? 'running') as AgentTask['status']),
    confidence: typeof payload.confidence === 'number' ? payload.confidence : 0.8,
  }
}

function mapAssetType(value: string): Asset['type'] {
  const normalized = value.toLowerCase()
  if (normalized === 'image') return 'Image'
  if (normalized === 'code') return 'Code'
  if (normalized === 'text') return 'Text'
  if (normalized === 'video') return 'Video'
  if (normalized === 'dataset') return 'Dataset'
  if (normalized === 'workflow') return 'Workflow'
  return 'Document'
}
