import { create } from 'zustand'

type MissionControlStore = {
  open: boolean
  setOpen: (open: boolean) => void
}

export const useMissionControlStore = create<MissionControlStore>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}))
