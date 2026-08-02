import { create } from 'zustand'
import type { ApiError, ApiStatus } from '../api/types'
import { workspaceService } from '../services/WorkspaceService'
import { toApiError } from '../services/types'
import type { Studio } from '../types/domain'

type WorkspaceStore = {
  selectedProjectId: string
  selectedStudioId: string
  inspectorOpen: boolean
  studios: Studio[]
  studiosStatus: ApiStatus
  studiosError: ApiError | null
  studiosLastLoadedAt: number | null
  setSelectedProjectId: (projectId: string) => void
  setSelectedStudioId: (studioId: string) => void
  toggleInspector: () => void
  loadStudios: () => Promise<void>
  refreshStudios: () => Promise<void>
}

export const useWorkspaceStore = create<WorkspaceStore>((set) => ({
  selectedProjectId: 'p1',
  selectedStudioId: 's1',
  inspectorOpen: true,
  studios: [],
  studiosStatus: 'idle',
  studiosError: null,
  studiosLastLoadedAt: null,
  setSelectedProjectId: (selectedProjectId) => set({ selectedProjectId }),
  setSelectedStudioId: (selectedStudioId) => set({ selectedStudioId }),
  toggleInspector: () => set((state) => ({ inspectorOpen: !state.inspectorOpen })),
  loadStudios: async () => {
    set((state) => ({ studiosStatus: state.studios.length > 0 ? 'refreshing' : 'loading', studiosError: null }))
    try {
      const studios = await workspaceService.listStudios()
      set({
        studios,
        studiosStatus: studios.length === 0 ? 'empty' : 'success',
        studiosError: null,
        studiosLastLoadedAt: Date.now(),
      })
    } catch (error) {
      set({ studiosStatus: 'error', studiosError: toApiError(error) })
    }
  },
  refreshStudios: async () => {
    await useWorkspaceStore.getState().loadStudios()
  },
}))
