import { create } from 'zustand'

import type {
  ApiError,
  ApiStatus,
  AutomationConflict,
  AutomationLog,
  AutomationRule,
  AutomationRuleRequest,
  AutomationRuleUpdateRequest,
  AutomationRun,
  AutomationState,
} from '../api/types'
import { automationService } from '../services/AutomationService'
import { toApiError } from '../services/types'

type AutomationStore = {
  rules: AutomationRule[]
  activeRule: AutomationRule | null
  history: AutomationRun[]
  logs: AutomationLog[]
  state: AutomationState | null
  conflicts: AutomationConflict[]
  lastRun: AutomationRun | null
  status: ApiStatus
  error: ApiError | null
  loadRules: (projectId?: string) => Promise<void>
  createRule: (request: AutomationRuleRequest) => Promise<AutomationRule | null>
  updateRule: (id: string, request: AutomationRuleUpdateRequest) => Promise<void>
  deleteRule: (id: string) => Promise<void>
  toggleRule: (id: string, enabled: boolean) => Promise<void>
  runRule: (id: string, agentId?: string) => Promise<void>
  dryRunRule: (id: string, agentId?: string) => Promise<void>
  loadHistory: (ruleId: string) => Promise<void>
  loadLogs: (ruleId: string) => Promise<void>
  loadConflicts: (projectId?: string) => Promise<void>
  setActiveRule: (rule: AutomationRule | null) => void
}

export const useAutomationStore = create<AutomationStore>((set, get) => ({
  rules: [],
  activeRule: null,
  history: [],
  logs: [],
  state: null,
  conflicts: [],
  lastRun: null,
  status: 'idle',
  error: null,
  loadRules: async (projectId) => {
    set({ status: 'loading', error: null })
    try {
      const rules = await automationService.listRules(projectId)
      const active = get().activeRule
      const nextActive = rules.find((rule) => rule.id === active?.id) ?? rules[0] ?? null
      set({
        rules,
        activeRule: nextActive,
        status: rules.length === 0 ? 'empty' : 'success',
        error: null,
      })
      if (nextActive) {
        await get().loadHistory(nextActive.id)
        await get().loadLogs(nextActive.id)
      }
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  createRule: async (request) => {
    set({ status: 'refreshing', error: null })
    try {
      const rule = await automationService.createRule(request)
      set((current) => ({
        rules: [rule, ...current.rules],
        activeRule: rule,
        status: 'success',
        error: null,
      }))
      await get().loadHistory(rule.id)
      return rule
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  updateRule: async (id, request) => {
    set({ status: 'refreshing', error: null })
    try {
      const updated = await automationService.updateRule(id, request)
      set((current) => ({
        rules: current.rules.map((rule) => (rule.id === id ? updated : rule)),
        activeRule: current.activeRule?.id === id ? updated : current.activeRule,
        status: 'success',
        error: null,
      }))
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  deleteRule: async (id) => {
    set({ status: 'refreshing', error: null })
    try {
      await automationService.deleteRule(id)
      set((current) => {
        const rules = current.rules.filter((rule) => rule.id !== id)
        return {
          rules,
          activeRule: current.activeRule?.id === id ? (rules[0] ?? null) : current.activeRule,
          history: current.activeRule?.id === id ? [] : current.history,
          logs: current.activeRule?.id === id ? [] : current.logs,
          status: 'success',
          error: null,
        }
      })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  toggleRule: async (id, enabled) => {
    set({ status: 'refreshing', error: null })
    try {
      const updated = enabled
        ? await automationService.enableRule(id)
        : await automationService.disableRule(id)
      set((current) => ({
        rules: current.rules.map((rule) => (rule.id === id ? updated : rule)),
        activeRule: current.activeRule?.id === id ? updated : current.activeRule,
        status: 'success',
        error: null,
      }))
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  runRule: async (id, agentId) => {
    set({ status: 'refreshing', error: null })
    try {
      const run = await automationService.runRule(id, { agentId })
      set({ lastRun: run, status: 'success', error: null })
      await get().loadHistory(id)
      await get().loadLogs(id)
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  dryRunRule: async (id, agentId) => {
    set({ status: 'refreshing', error: null })
    try {
      const run = await automationService.dryRunRule(id, { agentId })
      set({ lastRun: run, status: 'success', error: null })
      await get().loadHistory(id)
      await get().loadLogs(id)
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  loadHistory: async (ruleId) => {
    try {
      const [history, state] = await Promise.all([
        automationService.history(ruleId),
        automationService.state(ruleId),
      ])
      set({ history, state })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  loadLogs: async (ruleId) => {
    try {
      const logs = await automationService.listLogs({ ruleId })
      set({ logs })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  loadConflicts: async (projectId) => {
    try {
      const conflicts = await automationService.listConflicts(projectId)
      set({ conflicts })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  setActiveRule: (rule) => {
    set({ activeRule: rule, lastRun: null })
    if (rule) {
      void get().loadHistory(rule.id)
      void get().loadLogs(rule.id)
    } else {
      set({ history: [], logs: [], state: null })
    }
  },
}))
