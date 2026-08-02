import { create } from 'zustand'

import { activityService } from '../services/ActivityService'
import { toApiError } from '../services/types'
import type { ApiError, ApiStatus } from '../api/types'
import type { AgentTask, Job } from '../types/domain'

type ActivityStore = {
  jobs: Job[]
  agentTasks: AgentTask[]
  status: ApiStatus
  error: ApiError | null
  lastLoadedAt: number | null
  loadActivity: () => Promise<void>
  refreshActivity: () => Promise<void>
}

export const useActivityStore = create<ActivityStore>((set) => ({
  jobs: [],
  agentTasks: [],
  status: 'idle',
  error: null,
  lastLoadedAt: null,
  loadActivity: async () => {
    set((state) => ({ status: state.jobs.length > 0 ? 'refreshing' : 'loading', error: null }))
    try {
      const [jobs, agentTasks] = await Promise.all([activityService.listJobs(), activityService.listAgentTasks()])
      set({
        jobs,
        agentTasks,
        status: jobs.length === 0 ? 'empty' : 'success',
        error: null,
        lastLoadedAt: Date.now(),
      })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  refreshActivity: async () => {
    await useActivityStore.getState().loadActivity()
  },
}))
