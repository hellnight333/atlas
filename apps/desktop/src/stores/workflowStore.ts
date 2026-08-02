import { create } from 'zustand'

import type { ApiError, ApiStatus, WorkflowDefinitionPayload, WorkflowExecutionPayload } from '../api/types'
import { workflowService } from '../services/WorkflowService'
import { toApiError } from '../services/types'

type WorkflowStore = {
  workflows: WorkflowDefinitionPayload[]
  currentExecution: WorkflowExecutionPayload | null
  timeline: Array<Record<string, unknown>>
  status: ApiStatus
  error: ApiError | null
  loadWorkflows: () => Promise<void>
  createWorkflow: (definition: WorkflowDefinitionPayload) => Promise<WorkflowDefinitionPayload | null>
  executeWorkflow: (id: string) => Promise<WorkflowExecutionPayload | null>
  refreshExecution: (id: string) => Promise<void>
}

export const useWorkflowStore = create<WorkflowStore>((set) => ({
  workflows: [],
  currentExecution: null,
  timeline: [],
  status: 'idle',
  error: null,
  loadWorkflows: async () => {
    set({ status: 'loading', error: null })
    try {
      const workflows = await workflowService.list()
      set({ workflows, status: workflows.length === 0 ? 'empty' : 'success', error: null })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  createWorkflow: async (definition) => {
    set({ status: 'refreshing', error: null })
    try {
      const created = await workflowService.create(definition)
      set((state) => ({ workflows: [created, ...state.workflows], status: 'success', error: null }))
      return created
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  executeWorkflow: async (id) => {
    set({ status: 'refreshing', error: null })
    try {
      const execution = await workflowService.executeDefinition(id)
      const timeline = await workflowService.getExecutionTimeline(execution.id)
      set({ currentExecution: execution, timeline, status: 'success', error: null })
      return execution
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  refreshExecution: async (id) => {
    try {
      const execution = await workflowService.getExecution(id)
      const timeline = await workflowService.getExecutionTimeline(id)
      set({ currentExecution: execution ?? null, timeline })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
}))