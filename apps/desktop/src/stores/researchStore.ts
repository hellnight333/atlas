import { create } from 'zustand'

import type { ApiError, ApiStatus, ResearchGraph, ResearchSession } from '../api/types'
import { researchService } from '../services/ResearchService'
import { toApiError } from '../services/types'

type ResearchStore = {
  sessions: ResearchSession[]
  activeSession: ResearchSession | null
  graph: ResearchGraph | null
  sources: Array<Record<string, unknown>>
  findings: Array<Record<string, unknown>>
  report: Record<string, unknown> | null
  status: ApiStatus
  error: ApiError | null
  loadSessions: (projectId?: string) => Promise<void>
  createSession: (projectId: string, title: string, question: string) => Promise<ResearchSession | null>
  loadSession: (sessionId: string) => Promise<void>
  search: (sessionId: string, query: string, provider?: string) => Promise<void>
  summarize: (sessionId: string, sourceAssetIds: string[], prompt?: string) => Promise<void>
  generateReport: (sessionId: string, format?: 'markdown' | 'text' | 'pdf') => Promise<void>
  loadGraph: (projectId: string) => Promise<void>
}

export const useResearchStore = create<ResearchStore>((set) => ({
  sessions: [],
  activeSession: null,
  graph: null,
  sources: [],
  findings: [],
  report: null,
  status: 'idle',
  error: null,
  loadSessions: async (projectId) => {
    set({ status: 'loading', error: null })
    try {
      const sessions = await researchService.listSessions(projectId)
      set({ sessions, activeSession: sessions[0] ?? null, status: sessions.length === 0 ? 'empty' : 'success', error: null })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  createSession: async (projectId, title, question) => {
    set({ status: 'refreshing', error: null })
    try {
      const session = await researchService.createSession({ projectId, title, question })
      set((state) => ({ sessions: [session, ...state.sessions], activeSession: session, status: 'success', error: null }))
      return session
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  loadSession: async (sessionId) => {
    set({ status: 'loading', error: null })
    try {
      const session = await researchService.getSession(sessionId)
      set({ activeSession: session ?? null, status: session ? 'success' : 'empty', error: null })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  search: async (sessionId, query, provider = 'mock-search') => {
    set({ status: 'refreshing', error: null })
    try {
      const result = await researchService.search({ sessionId, query, provider })
      set({ sources: result.sources, status: 'success', error: null })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  summarize: async (sessionId, sourceAssetIds, prompt) => {
    set({ status: 'refreshing', error: null })
    try {
      const result = await researchService.summarize({ sessionId, sourceAssetIds, prompt })
      set((state) => ({ findings: [result.asset, ...state.findings], status: 'success', error: null }))
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  generateReport: async (sessionId, format = 'markdown') => {
    set({ status: 'refreshing', error: null })
    try {
      const report = await researchService.report({ sessionId, format })
      set({ report, status: 'success', error: null })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  loadGraph: async (projectId) => {
    try {
      const graph = await researchService.getGraph(projectId)
      set({ graph })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
}))