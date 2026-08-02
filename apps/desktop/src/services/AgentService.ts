import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  Agent,
  AgentMessage,
  AgentCreateRequest,
  AgentMemoryAttachRequest,
  AgentMemoryReference,
  AgentPlanRequest,
  AgentPermission,
  AgentTeam,
  AgentTeamCreateRequest,
  AgentTeamStatusPayload,
  ExecutionSchedule,
  RuntimeExecutionRecord,
  QueueUpdateResult,
  ScheduleQueueEntry,
  SchedulerCreateRequest,
  AgentUpdateRequest,
  PlannerExecutionPlan,
} from '../api/types'

export interface AgentService {
  list(projectId?: string): Promise<Agent[]>
  getById(id: string): Promise<Agent | undefined>
  create(request: AgentCreateRequest): Promise<Agent>
  update(id: string, request: AgentUpdateRequest): Promise<Agent>
  remove(id: string): Promise<void>
  listMemory(id: string): Promise<AgentMemoryReference[]>
  attachMemory(id: string, request: AgentMemoryAttachRequest): Promise<AgentMemoryReference>
  permissions(id: string): Promise<AgentPermission[]>
  generatePlan(id: string, request: AgentPlanRequest): Promise<PlannerExecutionPlan>
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
  createTeam(request: AgentTeamCreateRequest): Promise<AgentTeam>
  getTeam(id: string): Promise<AgentTeam | undefined>
  getTeamMessages(id: string): Promise<AgentMessage[]>
  cancelTeam(id: string): Promise<AgentTeam>
  getTeamStatus(id: string): Promise<AgentTeamStatusPayload>
}

export const agentService: AgentService = {
  async list(projectId) {
    return getAtlasProvider().listAgents(projectId)
  },
  async getById(id) {
    return getAtlasProvider().getAgent(id)
  },
  async create(request) {
    return getAtlasProvider().createAgent(request)
  },
  async update(id, request) {
    return getAtlasProvider().updateAgent(id, request)
  },
  async remove(id) {
    await getAtlasProvider().deleteAgent(id)
  },
  async listMemory(id) {
    return getAtlasProvider().listAgentMemory(id)
  },
  async attachMemory(id, request) {
    return getAtlasProvider().attachAgentMemory(id, request)
  },
  async permissions(id) {
    return getAtlasProvider().getAgentPermissions(id)
  },
  async generatePlan(id, request) {
    return getAtlasProvider().generateAgentPlan(id, request)
  },
  async createSchedule(request) {
    return getAtlasProvider().createSchedule(request)
  },
  async getSchedule(id) {
    return getAtlasProvider().getSchedule(id)
  },
  async getScheduleQueue(id) {
    return getAtlasProvider().getScheduleQueue(id)
  },
  async pauseSchedule(id) {
    return getAtlasProvider().pauseSchedule(id)
  },
  async resumeSchedule(id) {
    return getAtlasProvider().resumeSchedule(id)
  },
  async cancelSchedule(id) {
    return getAtlasProvider().cancelSchedule(id)
  },
  async startRuntimeSchedule(id) {
    return getAtlasProvider().startRuntimeSchedule(id)
  },
  async listRuntime() {
    return getAtlasProvider().listRuntime()
  },
  async listRuntimeRunning() {
    return getAtlasProvider().listRuntimeRunning()
  },
  async listRuntimeHistory() {
    return getAtlasProvider().listRuntimeHistory()
  },
  async getRuntimeExecution(id) {
    return getAtlasProvider().getRuntimeExecution(id)
  },
  async cancelRuntimeExecution(id) {
    return getAtlasProvider().cancelRuntimeExecution(id)
  },
  async retryRuntimeExecution(id) {
    return getAtlasProvider().retryRuntimeExecution(id)
  },
  async createTeam(request) {
    return getAtlasProvider().createAgentTeam(request)
  },
  async getTeam(id) {
    return getAtlasProvider().getAgentTeam(id)
  },
  async getTeamMessages(id) {
    return getAtlasProvider().getAgentTeamMessages(id)
  },
  async cancelTeam(id) {
    return getAtlasProvider().cancelAgentTeam(id)
  },
  async getTeamStatus(id) {
    return getAtlasProvider().getAgentTeamStatus(id)
  },
}
