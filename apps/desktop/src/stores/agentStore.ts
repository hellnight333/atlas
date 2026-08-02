import { create } from 'zustand'

import type {
  Agent,
  AgentAssignmentRequest,
  AgentMessage,
  AgentCreateRequest,
  AgentMemoryReference,
  AgentPermission,
  AgentTeam,
  AgentTeamStatusPayload,
  ExecutionSchedule,
  PlannerExecutionPlan,
  QueueUpdateResult,
  RuntimeExecutionRecord,
  ScheduleQueueEntry,
  SchedulerPriority,
  AgentUpdateRequest,
  ApiError,
  ApiStatus,
} from '../api/types'
import { agentService } from '../services/AgentService'
import { toApiError } from '../services/types'

type AgentStore = {
  agents: Agent[]
  activeAgent: Agent | null
  memoryRefs: AgentMemoryReference[]
  permissions: AgentPermission[]
  latestPlan: PlannerExecutionPlan | null
  latestSchedule: ExecutionSchedule | null
  scheduleQueue: ScheduleQueueEntry[]
  runtimeExecutions: RuntimeExecutionRecord[]
  runningExecutions: RuntimeExecutionRecord[]
  runtimeHistory: RuntimeExecutionRecord[]
  selectedRuntimeExecution: RuntimeExecutionRecord | null
  activeTeam: AgentTeam | null
  teamMessages: AgentMessage[]
  teamStatus: AgentTeamStatusPayload | null
  status: ApiStatus
  error: ApiError | null
  loadAgents: (projectId?: string) => Promise<void>
  createAgent: (request: AgentCreateRequest) => Promise<Agent | null>
  updateAgent: (id: string, request: AgentUpdateRequest) => Promise<Agent | null>
  deleteAgent: (id: string) => Promise<void>
  loadMemory: (id: string) => Promise<void>
  attachMemory: (id: string, kind: string, assetId: string) => Promise<void>
  loadPermissions: (id: string) => Promise<void>
  generatePlan: (id: string, goal: string) => Promise<PlannerExecutionPlan | null>
  createSchedule: (id: string, goal: string, priority?: SchedulerPriority) => Promise<ExecutionSchedule | null>
  loadSchedule: (id: string) => Promise<ExecutionSchedule | null>
  pauseSchedule: (id: string) => Promise<QueueUpdateResult | null>
  resumeSchedule: (id: string) => Promise<QueueUpdateResult | null>
  cancelSchedule: (id: string) => Promise<QueueUpdateResult | null>
  startRuntimeSchedule: (scheduleId: string) => Promise<RuntimeExecutionRecord[]>
  loadRuntime: () => Promise<void>
  cancelRuntimeExecution: (executionId: string) => Promise<RuntimeExecutionRecord | null>
  retryRuntimeExecution: (executionId: string) => Promise<RuntimeExecutionRecord | null>
  createTeam: (name: string, assignments: AgentAssignmentRequest[]) => Promise<AgentTeam | null>
  loadTeam: (teamId: string) => Promise<AgentTeam | null>
  cancelTeam: (teamId: string) => Promise<AgentTeam | null>
  setActiveAgent: (agent: Agent | null) => void
}

export const useAgentStore = create<AgentStore>((set, get) => ({
  agents: [],
  activeAgent: null,
  memoryRefs: [],
  permissions: [],
  latestPlan: null,
  latestSchedule: null,
  scheduleQueue: [],
  runtimeExecutions: [],
  runningExecutions: [],
  runtimeHistory: [],
  selectedRuntimeExecution: null,
  activeTeam: null,
  teamMessages: [],
  teamStatus: null,
  status: 'idle',
  error: null,
  loadAgents: async (projectId) => {
    set((state) => ({ status: state.agents.length > 0 ? 'refreshing' : 'loading', error: null }))
    try {
      const agents = await agentService.list(projectId)
      const active = agents[0] ?? null
      set({
        agents,
        activeAgent: active,
        status: agents.length === 0 ? 'empty' : 'success',
        error: null,
      })
      if (active) {
        void get().loadMemory(active.id)
        void get().loadPermissions(active.id)
      } else {
        set({ memoryRefs: [], permissions: [] })
      }
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  createAgent: async (request) => {
    set({ status: 'refreshing', error: null })
    try {
      const created = await agentService.create(request)
      set((state) => ({
        agents: [created, ...state.agents],
        activeAgent: created,
        status: 'success',
        error: null,
      }))
      await get().loadMemory(created.id)
      await get().loadPermissions(created.id)
      return created
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  updateAgent: async (id, request) => {
    set({ status: 'refreshing', error: null })
    try {
      const updated = await agentService.update(id, request)
      set((state) => ({
        agents: state.agents.map((agent) => (agent.id === id ? updated : agent)),
        activeAgent: state.activeAgent?.id === id ? updated : state.activeAgent,
        status: 'success',
        error: null,
      }))
      await get().loadPermissions(id)
      return updated
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  deleteAgent: async (id) => {
    set({ status: 'refreshing', error: null })
    try {
      await agentService.remove(id)
      set((state) => {
        const nextAgents = state.agents.filter((agent) => agent.id !== id)
        const nextActive = state.activeAgent?.id === id ? (nextAgents[0] ?? null) : state.activeAgent
        return {
          agents: nextAgents,
          activeAgent: nextActive,
          status: nextAgents.length === 0 ? 'empty' : 'success',
          error: null,
          memoryRefs: nextActive ? state.memoryRefs : [],
          permissions: nextActive ? state.permissions : [],
        }
      })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  loadMemory: async (id) => {
    try {
      const memoryRefs = await agentService.listMemory(id)
      set({ memoryRefs })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  attachMemory: async (id, kind, assetId) => {
    set({ status: 'refreshing', error: null })
    try {
      await agentService.attachMemory(id, { kind, assetId })
      set({ status: 'success', error: null })
      await get().loadMemory(id)
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  loadPermissions: async (id) => {
    try {
      const permissions = await agentService.permissions(id)
      set({ permissions })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  generatePlan: async (id, goal) => {
    set({ status: 'refreshing', error: null })
    try {
      const latestPlan = await agentService.generatePlan(id, { goal })
      set({ latestPlan, status: 'success', error: null })
      return latestPlan
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  createSchedule: async (id, goal, priority = 'normal') => {
    set({ status: 'refreshing', error: null })
    try {
      const latestSchedule = await agentService.createSchedule({ agentId: id, goal, priority })
      const scheduleQueue = latestSchedule.queue_entries
      set({ latestSchedule, scheduleQueue, status: 'success', error: null })
      return latestSchedule
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  loadSchedule: async (id) => {
    try {
      const latestSchedule = await agentService.getSchedule(id)
      const scheduleQueue = await agentService.getScheduleQueue(id)
      set({ latestSchedule, scheduleQueue, error: null })
      return latestSchedule
    } catch (error) {
      set({ error: toApiError(error) })
      return null
    }
  },
  pauseSchedule: async (id) => {
    set({ status: 'refreshing', error: null })
    try {
      const result = await agentService.pauseSchedule(id)
      const scheduleQueue = await agentService.getScheduleQueue(id)
      set({ scheduleQueue, status: 'success', error: null })
      return result
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  resumeSchedule: async (id) => {
    set({ status: 'refreshing', error: null })
    try {
      const result = await agentService.resumeSchedule(id)
      const scheduleQueue = await agentService.getScheduleQueue(id)
      set({ scheduleQueue, status: 'success', error: null })
      return result
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  cancelSchedule: async (id) => {
    set({ status: 'refreshing', error: null })
    try {
      const result = await agentService.cancelSchedule(id)
      const scheduleQueue = await agentService.getScheduleQueue(id)
      set({ scheduleQueue, status: 'success', error: null })
      return result
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  startRuntimeSchedule: async (scheduleId) => {
    set({ status: 'refreshing', error: null })
    try {
      const runtimeExecutions = await agentService.startRuntimeSchedule(scheduleId)
      const [runningExecutions, runtimeHistory] = await Promise.all([
        agentService.listRuntimeRunning(),
        agentService.listRuntimeHistory(),
      ])
      set({
        runtimeExecutions,
        runningExecutions,
        runtimeHistory,
        selectedRuntimeExecution: runtimeExecutions[0] ?? null,
        status: 'success',
        error: null,
      })
      return runtimeExecutions
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return []
    }
  },
  loadRuntime: async () => {
    try {
      const [runtimeExecutions, runningExecutions, runtimeHistory] = await Promise.all([
        agentService.listRuntime(),
        agentService.listRuntimeRunning(),
        agentService.listRuntimeHistory(),
      ])
      set({
        runtimeExecutions,
        runningExecutions,
        runtimeHistory,
        selectedRuntimeExecution: runningExecutions[0] ?? runtimeExecutions[0] ?? null,
        error: null,
      })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  cancelRuntimeExecution: async (executionId) => {
    set({ status: 'refreshing', error: null })
    try {
      const updated = await agentService.cancelRuntimeExecution(executionId)
      await get().loadRuntime()
      set({ status: 'success', error: null, selectedRuntimeExecution: updated })
      return updated
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  retryRuntimeExecution: async (executionId) => {
    set({ status: 'refreshing', error: null })
    try {
      const updated = await agentService.retryRuntimeExecution(executionId)
      await get().loadRuntime()
      set({ status: 'success', error: null, selectedRuntimeExecution: updated })
      return updated
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  createTeam: async (name, assignments) => {
    set({ status: 'refreshing', error: null })
    try {
      const projectId = get().activeAgent?.project_id ?? get().agents[0]?.project_id ?? undefined
      const team = await agentService.createTeam({ name, projectId, assignments })
      const [messages, teamStatus] = await Promise.all([
        agentService.getTeamMessages(team.id),
        agentService.getTeamStatus(team.id),
      ])
      set({ activeTeam: team, teamMessages: messages, teamStatus, status: 'success', error: null })
      return team
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  loadTeam: async (teamId) => {
    try {
      const team = await agentService.getTeam(teamId)
      if (!team) {
        set({ activeTeam: null, teamMessages: [], teamStatus: null })
        return null
      }
      const [messages, teamStatus] = await Promise.all([
        agentService.getTeamMessages(team.id),
        agentService.getTeamStatus(team.id),
      ])
      set({ activeTeam: team, teamMessages: messages, teamStatus, error: null })
      return team
    } catch (error) {
      set({ error: toApiError(error) })
      return null
    }
  },
  cancelTeam: async (teamId) => {
    set({ status: 'refreshing', error: null })
    try {
      const team = await agentService.cancelTeam(teamId)
      const [messages, teamStatus] = await Promise.all([
        agentService.getTeamMessages(team.id),
        agentService.getTeamStatus(team.id),
      ])
      set({ activeTeam: team, teamMessages: messages, teamStatus, status: 'success', error: null })
      return team
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  setActiveAgent: (agent) => {
    set({ activeAgent: agent })
    if (agent) {
      void get().loadMemory(agent.id)
      void get().loadPermissions(agent.id)
    } else {
      set({ memoryRefs: [], permissions: [] })
    }
  },
}))
