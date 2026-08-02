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
  ApprovalCreatePayload,
  AuditAction,
  AuditRecord,
  IdentityProviderStatus,
  MemberAddPayload,
  OrgIdentity,
  OrgMembership,
  OrgPermission,
  OrgPolicySet,
  OrgRole,
  OrgTeam,
  Organization,
  OrganizationCreatePayload,
  OrganizationDetail,
  PermissionResolution,
  PolicyDomain,
  PolicySetPayload,
  ResolvedPolicy,
  TeamKind,
  ClusterHealth,
  ClusterLoad,
  ClusterSnapshot,
  ClusterSweepResult,
  ExecutionLease,
  ExecutionReservation,
  WorkerDetail,
  WorkerHeartbeatPayload,
  WorkerNode,
  WorkerRegisterPayload,
  WorkerStatus,
  ApprovalDecisionPayload,
  ApprovalHistoryEvent,
  ApprovalPolicy,
  ApprovalRequest,
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

  async listAutomationRules(projectId?: string): Promise<AutomationRule[]> {
    const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    return this.client.get(`${atlasEndpoints.automation}${suffix}`)
  }

  async getAutomationRule(id: string): Promise<AutomationRule | undefined> {
    return this.client.get(atlasEndpoints.automationById(id))
  }

  async createAutomationRule(request: AutomationRuleRequest): Promise<AutomationRule> {
    return this.client.post(atlasEndpoints.automation, {
      name: request.name,
      description: request.description ?? '',
      trigger: request.trigger,
      conditions: request.conditions ?? [],
      actions: request.actions ?? [],
      project_id: request.projectId,
      workspace_id: request.workspaceId,
      schedule: request.schedule,
      priority: request.priority ?? 0,
      dry_run: request.dryRun ?? false,
      actor: request.actor ?? 'system',
    })
  }

  async updateAutomationRule(id: string, request: AutomationRuleUpdateRequest): Promise<AutomationRule> {
    const body: Record<string, unknown> = { actor: request.actor ?? 'system' }
    if (request.name !== undefined) body.name = request.name
    if (request.description !== undefined) body.description = request.description
    if (request.trigger !== undefined) body.trigger = request.trigger
    if (request.conditions !== undefined) body.conditions = request.conditions
    if (request.actions !== undefined) body.actions = request.actions
    if (request.schedule !== undefined) body.schedule = request.schedule
    if (request.priority !== undefined) body.priority = request.priority
    if (request.dryRun !== undefined) body.dry_run = request.dryRun
    return this.client.put(atlasEndpoints.automationById(id), body)
  }

  async deleteAutomationRule(id: string): Promise<void> {
    await this.client.delete(atlasEndpoints.automationById(id))
  }

  async enableAutomationRule(id: string): Promise<AutomationRule> {
    return this.client.post(atlasEndpoints.automationEnable(id), {})
  }

  async disableAutomationRule(id: string): Promise<AutomationRule> {
    return this.client.post(atlasEndpoints.automationDisable(id), {})
  }

  async runAutomationRule(id: string, request?: AutomationRunRequest): Promise<AutomationRun> {
    return this.client.post(atlasEndpoints.automationRun(id), {
      trigger_data: request?.triggerData ?? {},
      agent_id: request?.agentId,
      actor: request?.actor ?? 'system',
    })
  }

  async dryRunAutomationRule(id: string, request?: AutomationRunRequest): Promise<AutomationRun> {
    return this.client.post(atlasEndpoints.automationDryRun(id), {
      trigger_data: request?.triggerData ?? {},
      agent_id: request?.agentId,
      actor: request?.actor ?? 'system',
    })
  }

  async getAutomationHistory(id: string): Promise<AutomationRun[]> {
    return this.client.get(atlasEndpoints.automationHistory(id))
  }

  async getAutomationState(id: string): Promise<AutomationState> {
    return this.client.get(atlasEndpoints.automationState(id))
  }

  async listAutomationRuns(ruleId?: string): Promise<AutomationRun[]> {
    const suffix = ruleId ? `?rule_id=${encodeURIComponent(ruleId)}` : ''
    return this.client.get(`${atlasEndpoints.automationRuns}${suffix}`)
  }

  async listAutomationLogs(params?: { runId?: string; ruleId?: string }): Promise<AutomationLog[]> {
    const query = new URLSearchParams()
    if (params?.runId) query.set('run_id', params.runId)
    if (params?.ruleId) query.set('rule_id', params.ruleId)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return this.client.get(`${atlasEndpoints.automationLogs}${suffix}`)
  }

  async listAutomationConflicts(projectId?: string): Promise<AutomationConflict[]> {
    const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    return this.client.get(`${atlasEndpoints.automationConflicts}${suffix}`)
  }

  async listApprovals(params?: { pendingOnly?: boolean; projectId?: string }): Promise<ApprovalRequest[]> {
    const query = new URLSearchParams()
    if (params?.pendingOnly) query.set('pending_only', 'true')
    if (params?.projectId) query.set('project_id', params.projectId)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return this.client.get(`${atlasEndpoints.approvals}${suffix}`)
  }

  async getApproval(id: string): Promise<ApprovalRequest | undefined> {
    return this.client.get(atlasEndpoints.approvalById(id))
  }

  async createApproval(payload: ApprovalCreatePayload): Promise<ApprovalRequest> {
    return this.client.post(atlasEndpoints.approvals, {
      title: payload.title,
      action: payload.action ?? '',
      scopes: payload.scopes ?? [],
      estimated_cost: payload.estimatedCost ?? 0,
      project_id: payload.projectId,
      workspace_id: payload.workspaceId,
      agent_id: payload.agentId,
      execution_id: payload.executionId,
      schedule_id: payload.scheduleId,
      entry_id: payload.entryId,
      priority: payload.priority ?? 0,
      payload: payload.payload ?? {},
      metadata: payload.metadata ?? {},
      requested_by: payload.requestedBy ?? 'system',
    })
  }

  async approveApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest> {
    return this.client.post(atlasEndpoints.approvalApprove(id), payload)
  }

  async rejectApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest> {
    return this.client.post(atlasEndpoints.approvalReject(id), payload)
  }

  async requestChangesApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest> {
    return this.client.post(atlasEndpoints.approvalRequestChanges(id), payload)
  }

  async cancelApproval(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest> {
    return this.client.post(atlasEndpoints.approvalCancel(id), payload)
  }

  async viewApproval(id: string, actor: string): Promise<ApprovalRequest> {
    return this.client.post(atlasEndpoints.approvalView(id), { actor })
  }

  async escalateApproval(id: string, actor: string, escalatedTo: string): Promise<ApprovalRequest> {
    return this.client.post(atlasEndpoints.approvalEscalate(id), { actor, escalated_to: escalatedTo })
  }

  async resumeApprovedExecution(id: string): Promise<RuntimeExecutionRecord> {
    return this.client.post(atlasEndpoints.approvalResumeExecution(id), {})
  }

  async getApprovalHistory(approvalId?: string): Promise<ApprovalHistoryEvent[]> {
    const suffix = approvalId ? `?approval_id=${encodeURIComponent(approvalId)}` : ''
    return this.client.get(`${atlasEndpoints.approvalHistory}${suffix}`)
  }

  async listApprovalPolicies(projectId?: string): Promise<ApprovalPolicy[]> {
    const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    return this.client.get(`${atlasEndpoints.approvalPolicies}${suffix}`)
  }

  async upsertApprovalPolicy(policy: Partial<ApprovalPolicy> & { name: string }): Promise<ApprovalPolicy> {
    return this.client.put(atlasEndpoints.approvalPolicies, policy)
  }

  async listExecutionsWaitingApproval(): Promise<RuntimeExecutionRecord[]> {
    return this.client.get(atlasEndpoints.approvalWaitingExecutions)
  }

  async listWorkers(status?: WorkerStatus): Promise<WorkerNode[]> {
    const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
    return this.client.get(`${atlasEndpoints.workers}${suffix}`)
  }

  async getWorker(id: string): Promise<WorkerDetail | undefined> {
    return this.client.get(atlasEndpoints.workerById(id))
  }

  async registerWorker(payload: WorkerRegisterPayload): Promise<WorkerNode> {
    return this.client.post(atlasEndpoints.workerRegister, {
      hostname: payload.hostname,
      display_name: payload.displayName,
      platform: payload.platform ?? 'unknown',
      resources: payload.resources ?? {},
      capabilities: payload.capabilities ?? [],
      max_concurrency: payload.maxConcurrency ?? 1,
      version: payload.version ?? '0.0.0',
      tags: payload.tags ?? [],
      worker_id: payload.workerId,
    })
  }

  async sendWorkerHeartbeat(payload: WorkerHeartbeatPayload): Promise<WorkerNode> {
    return this.client.post(atlasEndpoints.workerHeartbeat, {
      worker_id: payload.workerId,
      status: payload.status,
      current_load: payload.currentLoad,
      metrics: payload.metrics,
    })
  }

  async pauseWorker(id: string): Promise<WorkerNode> {
    return this.client.post(atlasEndpoints.workerPause(id), {})
  }

  async resumeWorker(id: string): Promise<WorkerNode> {
    return this.client.post(atlasEndpoints.workerResume(id), {})
  }

  async drainWorker(id: string): Promise<WorkerNode> {
    return this.client.post(atlasEndpoints.workerDrain(id), {})
  }

  async getCluster(): Promise<ClusterSnapshot> {
    return this.client.get(atlasEndpoints.cluster)
  }

  async getClusterHealth(): Promise<ClusterHealth> {
    return this.client.get(atlasEndpoints.clusterHealth)
  }

  async getClusterLoad(): Promise<ClusterLoad> {
    return this.client.get(atlasEndpoints.clusterLoad)
  }

  async listReservations(workerId?: string): Promise<ExecutionReservation[]> {
    const suffix = workerId ? `?worker_id=${encodeURIComponent(workerId)}` : ''
    return this.client.get(`${atlasEndpoints.clusterReservations}${suffix}`)
  }

  async listLeases(workerId?: string): Promise<ExecutionLease[]> {
    const suffix = workerId ? `?worker_id=${encodeURIComponent(workerId)}` : ''
    return this.client.get(`${atlasEndpoints.clusterLeases}${suffix}`)
  }

  async listExecutionsWaitingPlacement(): Promise<RuntimeExecutionRecord[]> {
    return this.client.get(atlasEndpoints.clusterWaitingPlacement)
  }

  async sweepCluster(): Promise<ClusterSweepResult> {
    return this.client.post(atlasEndpoints.clusterSweep, {})
  }

  async recoverExecution(executionId: string, reason?: string): Promise<RuntimeExecutionRecord> {
    const suffix = reason ? `?reason=${encodeURIComponent(reason)}` : ''
    return this.client.post(`${atlasEndpoints.clusterRecover(executionId)}${suffix}`, {})
  }

  async retryPlacement(executionId: string): Promise<RuntimeExecutionRecord> {
    return this.client.post(atlasEndpoints.clusterRetryPlacement(executionId), {})
  }

  async listOrganizations(identityId?: string): Promise<Organization[]> {
    const suffix = identityId ? `?identity_id=${encodeURIComponent(identityId)}` : ''
    return this.client.get(`${atlasEndpoints.organizations}${suffix}`)
  }

  async getOrganization(id: string): Promise<OrganizationDetail | undefined> {
    return this.client.get(atlasEndpoints.organizationById(id))
  }

  async createOrganization(payload: OrganizationCreatePayload): Promise<Organization> {
    return this.client.post(atlasEndpoints.organizations, {
      name: payload.name,
      slug: payload.slug,
      description: payload.description ?? '',
      actor_id: payload.actorId ?? 'system',
    })
  }

  async updateOrganization(id: string, changes: Partial<Organization>): Promise<Organization> {
    return this.client.put(atlasEndpoints.organizationById(id), changes)
  }

  async listOrganizationMembers(id: string): Promise<OrgMembership[]> {
    return this.client.get(atlasEndpoints.organizationMembers(id))
  }

  async addOrganizationMember(id: string, payload: MemberAddPayload): Promise<OrgMembership> {
    return this.client.post(atlasEndpoints.organizationMembers(id), {
      identity_id: payload.identityId,
      role_ids: payload.roleIds ?? [],
      team_ids: payload.teamIds ?? [],
      scope: payload.scope ?? 'organization',
      scope_id: payload.scopeId,
      expires_at: payload.expiresAt,
      actor_id: payload.actorId ?? 'system',
    })
  }

  async removeOrganizationMember(organizationId: string, membershipId: string): Promise<void> {
    await this.client.delete(atlasEndpoints.organizationMember(organizationId, membershipId))
  }

  async resolveIdentityPermissions(
    organizationId: string,
    identityId: string,
  ): Promise<PermissionResolution> {
    return this.client.get(atlasEndpoints.organizationPermissions(organizationId, identityId))
  }

  async assignWorkerToOrganization(organizationId: string, workerId: string): Promise<void> {
    await this.client.post(atlasEndpoints.organizationWorker(organizationId, workerId), {
      organization_id: organizationId,
    })
  }

  async listOrgRoles(organizationId?: string): Promise<OrgRole[]> {
    const suffix = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''
    return this.client.get(`${atlasEndpoints.orgRoles}${suffix}`)
  }

  async createOrgRole(payload: {
    name: string
    permissions: OrgPermission[]
    organizationId?: string
    description?: string
  }): Promise<OrgRole> {
    return this.client.post(atlasEndpoints.orgRoles, {
      name: payload.name,
      permissions: payload.permissions,
      organization_id: payload.organizationId,
      description: payload.description ?? '',
    })
  }

  async updateOrgRole(roleId: string, permissions: OrgPermission[]): Promise<OrgRole> {
    return this.client.put(atlasEndpoints.orgRoleById(roleId), { permissions })
  }

  async listOrgPermissions(): Promise<Array<{ permission: OrgPermission; name: string }>> {
    return this.client.get(atlasEndpoints.orgPermissions)
  }

  async listOrgTeams(organizationId?: string): Promise<OrgTeam[]> {
    const suffix = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : ''
    return this.client.get(`${atlasEndpoints.orgTeams}${suffix}`)
  }

  async createOrgTeam(payload: {
    organizationId: string
    name: string
    kind?: TeamKind
    description?: string
  }): Promise<OrgTeam> {
    return this.client.post(atlasEndpoints.orgTeams, {
      organization_id: payload.organizationId,
      name: payload.name,
      kind: payload.kind ?? 'custom',
      description: payload.description ?? '',
    })
  }

  async listPolicySets(organizationId?: string, domain?: PolicyDomain): Promise<OrgPolicySet[]> {
    const query = new URLSearchParams()
    if (organizationId) query.set('organization_id', organizationId)
    if (domain) query.set('domain', domain)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return this.client.get(`${atlasEndpoints.policies}${suffix}`)
  }

  async upsertPolicySet(payload: PolicySetPayload): Promise<OrgPolicySet> {
    return this.client.put(atlasEndpoints.policies, {
      id: payload.id,
      organization_id: payload.organizationId,
      domain: payload.domain,
      scope: payload.scope ?? 'organization',
      scope_id: payload.scopeId,
      settings: payload.settings ?? {},
      locked_keys: payload.lockedKeys ?? [],
      enabled: payload.enabled ?? true,
      actor_id: payload.actorId ?? 'system',
    })
  }

  async resolvePolicy(params: {
    organizationId: string
    domain: PolicyDomain
    workspaceId?: string
    projectId?: string
    objectId?: string
  }): Promise<ResolvedPolicy> {
    const query = new URLSearchParams({
      organization_id: params.organizationId,
      domain: params.domain,
    })
    if (params.workspaceId) query.set('workspace_id', params.workspaceId)
    if (params.projectId) query.set('project_id', params.projectId)
    if (params.objectId) query.set('object_id', params.objectId)
    return this.client.get(`${atlasEndpoints.policiesResolve}?${query.toString()}`)
  }

  async listAuditRecords(params?: {
    organizationId?: string
    action?: AuditAction
    actorId?: string
    limit?: number
  }): Promise<AuditRecord[]> {
    const query = new URLSearchParams()
    if (params?.organizationId) query.set('organization_id', params.organizationId)
    if (params?.action) query.set('action', params.action)
    if (params?.actorId) query.set('actor_id', params.actorId)
    if (params?.limit) query.set('limit', String(params.limit))
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return this.client.get(`${atlasEndpoints.audit}${suffix}`)
  }

  async getAuditRecord(id: string): Promise<AuditRecord | undefined> {
    return this.client.get(atlasEndpoints.auditById(id))
  }

  async listIdentities(): Promise<OrgIdentity[]> {
    return this.client.get(atlasEndpoints.identities)
  }

  async createIdentity(payload: {
    subject: string
    displayName: string
    email?: string
  }): Promise<OrgIdentity> {
    return this.client.post(atlasEndpoints.identities, {
      subject: payload.subject,
      display_name: payload.displayName,
      email: payload.email,
    })
  }

  async listIdentityProviders(): Promise<IdentityProviderStatus[]> {
    return this.client.get(atlasEndpoints.identityProviders)
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
