import { create } from 'zustand'

type UIStore = {
  activityCenterOpen: boolean
  setActivityCenterOpen: (open: boolean) => void
}

export const useUIStore = create<UIStore>((set) => ({
  activityCenterOpen: false,
  setActivityCenterOpen: (activityCenterOpen) => set({ activityCenterOpen }),
}))
