import { create } from 'zustand'

type ThemeStore = {
  theme: 'atlas-dark'
}

export const useThemeStore = create<ThemeStore>(() => ({
  theme: 'atlas-dark',
}))
