import { create } from 'zustand'

import { mockPinnedCommandIds, mockRecentCommandIds } from '../mock/data'
import type { ApiError, ApiStatus } from '../api/types'
import { commandService } from '../services/CommandService'
import { toApiError } from '../services/types'
import type { CommandMode } from '../types/domain'
import type { CommandItem } from '../types/domain'

type CommandPaletteStore = {
  open: boolean
  mode: CommandMode
  query: string
  commands: CommandItem[]
  status: ApiStatus
  error: ApiError | null
  lastLoadedAt: number | null
  recentCommandIds: string[]
  pinnedCommandIds: string[]
  setOpen: (open: boolean) => void
  setMode: (mode: CommandMode) => void
  setQuery: (query: string) => void
  pushRecent: (commandId: string) => void
  loadCommands: () => Promise<void>
  refreshCommands: () => Promise<void>
}

export const useCommandPaletteStore = create<CommandPaletteStore>((set) => ({
  open: false,
  mode: 'command',
  query: '',
  commands: [],
  status: 'idle',
  error: null,
  lastLoadedAt: null,
  recentCommandIds: mockRecentCommandIds,
  pinnedCommandIds: mockPinnedCommandIds,
  setOpen: (open) => set({ open }),
  setMode: (mode) => set({ mode }),
  setQuery: (query) => set({ query }),
  pushRecent: (commandId) =>
    set((state) => ({
      recentCommandIds: [commandId, ...state.recentCommandIds.filter((item) => item !== commandId)].slice(0, 8),
    })),
  loadCommands: async () => {
    set((state) => ({ status: state.commands.length > 0 ? 'refreshing' : 'loading', error: null }))
    try {
      const commands = await commandService.list()
      set({
        commands,
        status: commands.length === 0 ? 'empty' : 'success',
        error: null,
        lastLoadedAt: Date.now(),
      })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  refreshCommands: async () => {
    await useCommandPaletteStore.getState().loadCommands()
  },
}))
