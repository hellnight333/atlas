import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  AutomationConflict,
  AutomationLog,
  AutomationRule,
  AutomationRuleRequest,
  AutomationRuleUpdateRequest,
  AutomationRun,
  AutomationRunRequest,
  AutomationState,
} from '../api/types'

export interface AutomationService {
  listRules(projectId?: string): Promise<AutomationRule[]>
  getRule(id: string): Promise<AutomationRule | undefined>
  createRule(request: AutomationRuleRequest): Promise<AutomationRule>
  updateRule(id: string, request: AutomationRuleUpdateRequest): Promise<AutomationRule>
  deleteRule(id: string): Promise<void>
  enableRule(id: string): Promise<AutomationRule>
  disableRule(id: string): Promise<AutomationRule>
  runRule(id: string, request?: AutomationRunRequest): Promise<AutomationRun>
  dryRunRule(id: string, request?: AutomationRunRequest): Promise<AutomationRun>
  history(id: string): Promise<AutomationRun[]>
  state(id: string): Promise<AutomationState>
  listRuns(ruleId?: string): Promise<AutomationRun[]>
  listLogs(params?: { runId?: string; ruleId?: string }): Promise<AutomationLog[]>
  listConflicts(projectId?: string): Promise<AutomationConflict[]>
}

export const automationService: AutomationService = {
  async listRules(projectId) {
    return getAtlasProvider().listAutomationRules(projectId)
  },
  async getRule(id) {
    return getAtlasProvider().getAutomationRule(id)
  },
  async createRule(request) {
    return getAtlasProvider().createAutomationRule(request)
  },
  async updateRule(id, request) {
    return getAtlasProvider().updateAutomationRule(id, request)
  },
  async deleteRule(id) {
    return getAtlasProvider().deleteAutomationRule(id)
  },
  async enableRule(id) {
    return getAtlasProvider().enableAutomationRule(id)
  },
  async disableRule(id) {
    return getAtlasProvider().disableAutomationRule(id)
  },
  async runRule(id, request) {
    return getAtlasProvider().runAutomationRule(id, request)
  },
  async dryRunRule(id, request) {
    return getAtlasProvider().dryRunAutomationRule(id, request)
  },
  async history(id) {
    return getAtlasProvider().getAutomationHistory(id)
  },
  async state(id) {
    return getAtlasProvider().getAutomationState(id)
  },
  async listRuns(ruleId) {
    return getAtlasProvider().listAutomationRuns(ruleId)
  },
  async listLogs(params) {
    return getAtlasProvider().listAutomationLogs(params)
  },
  async listConflicts(projectId) {
    return getAtlasProvider().listAutomationConflicts(projectId)
  },
}
