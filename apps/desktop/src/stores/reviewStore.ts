import { create } from 'zustand'

import type { ApiError, ApiStatus, ReviewHistoryEvent, ReviewSession } from '../api/types'
import { reviewService } from '../services/ReviewService'
import { toApiError } from '../services/types'

type ReviewStore = {
  sessions: ReviewSession[]
  activeSession: ReviewSession | null
  history: ReviewHistoryEvent[]
  status: ApiStatus
  error: ApiError | null
  loadSessions: (projectId?: string) => Promise<void>
  createSession: (projectId: string, title: string, assetId?: string) => Promise<ReviewSession | null>
  approve: (reviewId: string, assetId: string, comment?: string) => Promise<void>
  reject: (reviewId: string, assetId: string, comment?: string) => Promise<void>
  comment: (reviewId: string, content: string) => Promise<void>
  publish: (reviewId: string, assetId: string) => Promise<void>
  loadHistory: (reviewId: string) => Promise<void>
  setActiveSession: (review: ReviewSession | null) => void
}

export const useReviewStore = create<ReviewStore>((set, get) => ({
  sessions: [],
  activeSession: null,
  history: [],
  status: 'idle',
  error: null,
  loadSessions: async (projectId) => {
    set({ status: 'loading', error: null })
    try {
      const sessions = await reviewService.listSessions(projectId)
      set({
        sessions,
        activeSession: sessions[0] ?? null,
        status: sessions.length === 0 ? 'empty' : 'success',
        error: null,
      })
      if (sessions[0]) {
        void get().loadHistory(sessions[0].id)
      }
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  createSession: async (projectId, title, assetId) => {
    set({ status: 'refreshing', error: null })
    try {
      const session = await reviewService.createSession({ projectId, title, assetId })
      set((state) => ({
        sessions: [session, ...state.sessions],
        activeSession: session,
        status: 'success',
        error: null,
      }))
      await get().loadHistory(session.id)
      return session
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  approve: async (reviewId, assetId, comment) => {
    set({ status: 'refreshing', error: null })
    try {
      const updated = await reviewService.approve(reviewId, { assetId, comment })
      set((state) => ({
        sessions: state.sessions.map((session) => (session.id === reviewId ? updated : session)),
        activeSession: state.activeSession?.id === reviewId ? updated : state.activeSession,
        status: 'success',
        error: null,
      }))
      await get().loadHistory(reviewId)
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  reject: async (reviewId, assetId, comment) => {
    set({ status: 'refreshing', error: null })
    try {
      const updated = await reviewService.reject(reviewId, { assetId, comment })
      set((state) => ({
        sessions: state.sessions.map((session) => (session.id === reviewId ? updated : session)),
        activeSession: state.activeSession?.id === reviewId ? updated : state.activeSession,
        status: 'success',
        error: null,
      }))
      await get().loadHistory(reviewId)
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  comment: async (reviewId, content) => {
    set({ status: 'refreshing', error: null })
    try {
      await reviewService.comment(reviewId, { content })
      set({ status: 'success', error: null })
      await get().loadHistory(reviewId)
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  publish: async (reviewId, assetId) => {
    set({ status: 'refreshing', error: null })
    try {
      const payload = await reviewService.publish(reviewId, { assetId })
      const updated = payload as unknown as ReviewSession
      set((state) => ({
        sessions: state.sessions.map((session) => (session.id === reviewId ? updated : session)),
        activeSession: state.activeSession?.id === reviewId ? updated : state.activeSession,
        status: 'success',
        error: null,
      }))
      await get().loadHistory(reviewId)
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  loadHistory: async (reviewId) => {
    try {
      const history = await reviewService.history(reviewId)
      set({ history })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  setActiveSession: (review) => {
    set({ activeSession: review })
    if (review) {
      void get().loadHistory(review.id)
    } else {
      set({ history: [] })
    }
  },
}))