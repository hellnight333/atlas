import { create } from 'zustand'

import { projectService } from '../services/ProjectService'
import { toApiError } from '../services/types'
import type { ApiError, ApiStatus } from '../api/types'
import type { Project } from '../types/domain'

type ProjectStore = {
  projects: Project[]
  status: ApiStatus
  error: ApiError | null
  lastLoadedAt: number | null
  loadProjects: () => Promise<void>
  refreshProjects: () => Promise<void>
}

export const useProjectStore = create<ProjectStore>((set) => ({
  projects: [],
  status: 'idle',
  error: null,
  lastLoadedAt: null,
  loadProjects: async () => {
    set((state) => ({ status: state.projects.length > 0 ? 'refreshing' : 'loading', error: null }))
    try {
      const projects = await projectService.list()
      set({
        projects,
        status: projects.length === 0 ? 'empty' : 'success',
        error: null,
        lastLoadedAt: Date.now(),
      })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  refreshProjects: async () => {
    await useProjectStore.getState().loadProjects()
  },
}))
