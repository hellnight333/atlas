import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  WorkflowDefinitionPayload,
  WorkflowExecutionPayload,
  WorkflowExecutionRequest,
  WorkflowExecutionResult,
} from '../api/types'

export interface WorkflowService {
  list(): Promise<WorkflowDefinitionPayload[]>
  getById(id: string): Promise<WorkflowDefinitionPayload | undefined>
  create(definition: WorkflowDefinitionPayload): Promise<WorkflowDefinitionPayload>
  executeDefinition(id: string): Promise<WorkflowExecutionPayload>
  getExecution(id: string): Promise<WorkflowExecutionPayload | undefined>
  getExecutionTimeline(id: string): Promise<Array<Record<string, unknown>>>
  execute(request: WorkflowExecutionRequest): Promise<WorkflowExecutionResult>
}

export const workflowService: WorkflowService = {
  async list() {
    return getAtlasProvider().getWorkflows()
  },
  async getById(id) {
    return getAtlasProvider().getWorkflow(id)
  },
  async create(definition) {
    return getAtlasProvider().createWorkflow(definition)
  },
  async executeDefinition(id) {
    return getAtlasProvider().executeWorkflowDefinition(id)
  },
  async getExecution(id) {
    return getAtlasProvider().getExecution(id)
  },
  async getExecutionTimeline(id) {
    return getAtlasProvider().getExecutionTimeline(id)
  },
  async execute(request) {
    return getAtlasProvider().executeWorkflow(request)
  },
}
