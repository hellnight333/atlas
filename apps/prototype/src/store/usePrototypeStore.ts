import { create } from 'zustand'

import {
  agentTasks,
  assets,
  commands,
  jobs,
  notifications,
  pinnedCommandIds,
  projects,
  recentCommandIds,
  screens,
  studios,
} from '../data/mockData'
import type {
  CommandItem,
  CommandMode,
  NotificationItem,
  ScreenId,
} from '../types'

type PrototypeState = {
  activeScreen: ScreenId
  missionControlOpen: boolean
  commandPaletteOpen: boolean
  activityCenterOpen: boolean
  inspectorOpen: boolean
  commandMode: CommandMode
  commandQuery: string
  selectedProjectId: string
  selectedStudioId: string
  selectedAssetId: string
  commandHistory: string[]
  pinnedCommands: string[]
  notifications: NotificationItem[]
  navigate: (screen: ScreenId) => void
  toggleMissionControl: (next?: boolean) => void
  toggleCommandPalette: (next?: boolean) => void
  toggleActivityCenter: (next?: boolean) => void
  toggleInspector: () => void
  setCommandMode: (mode: CommandMode) => void
  setCommandQuery: (query: string) => void
  runCommand: (commandId: string) => void
}

const initialProjectId = projects[0]?.id ?? ''
const initialStudioId = studios[0]?.id ?? ''
const initialAssetId = assets[0]?.id ?? ''

export const usePrototypeStore = create<PrototypeState>((set, get) => ({
  activeScreen: 'desktop-overview',
  missionControlOpen: false,
  commandPaletteOpen: false,
  activityCenterOpen: false,
  inspectorOpen: true,
  commandMode: 'command',
  commandQuery: '',
  selectedProjectId: initialProjectId,
  selectedStudioId: initialStudioId,
  selectedAssetId: initialAssetId,
  commandHistory: recentCommandIds,
  pinnedCommands: pinnedCommandIds,
  notifications,
  navigate: (screen) => set({ activeScreen: screen }),
  toggleMissionControl: (next) =>
    set((state) => ({ missionControlOpen: typeof next === 'boolean' ? next : !state.missionControlOpen })),
  toggleCommandPalette: (next) =>
    set((state) => ({ commandPaletteOpen: typeof next === 'boolean' ? next : !state.commandPaletteOpen })),
  toggleActivityCenter: (next) =>
    set((state) => ({ activityCenterOpen: typeof next === 'boolean' ? next : !state.activityCenterOpen })),
  toggleInspector: () => set((state) => ({ inspectorOpen: !state.inspectorOpen })),
  setCommandMode: (mode) => set({ commandMode: mode }),
  setCommandQuery: (query) => set({ commandQuery: query }),
  runCommand: (commandId) => {
    const state = get()
    const command = commands.find((item) => item.id === commandId)
    if (!command) {
      return
    }

    const nextHistory = [commandId, ...state.commandHistory.filter((item) => item !== commandId)].slice(0, 8)

    set({ commandHistory: nextHistory, commandPaletteOpen: false, commandQuery: '' })

    const byLabel = (label: string): CommandItem | undefined => commands.find((item) => item.label === label)

    if (command.id === byLabel('Open Mission Control')?.id) {
      set({ missionControlOpen: true })
      return
    }

    if (command.id === byLabel('Open Activity Center')?.id) {
      set({ activityCenterOpen: true })
      return
    }

    if (command.id === byLabel('Switch to Research Studio')?.id) {
      const researchStudio = studios.find((studio) => studio.name === 'Research Studio')
      if (researchStudio) {
        set({ selectedStudioId: researchStudio.id, activeScreen: 'studio-workspace' })
      }
    }
  },
}))

export const prototypeData = {
  screens,
  projects,
  studios,
  assets,
  agentTasks,
  jobs,
  commands,
}
