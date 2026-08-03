import { create } from 'zustand'

import {
  ASSUMED_COMPLETE,
  onboardingService,
  type DemoInstallResult,
  type DemoSummary,
  type OnboardingState,
  type OnboardingStepId,
  type StepPayload,
  type ThemeChoice,
} from '../services/OnboardingService'

type Phase = 'idle' | 'loading' | 'ready' | 'working' | 'error'

type OnboardingStore = {
  state: OnboardingState | null
  demos: DemoSummary[]
  installed: Record<string, DemoInstallResult>
  phase: Phase
  /** Non-fatal message shown inline; setup continues. */
  error: string | null
  /** Which demo is mid-install, for a per-card spinner. */
  installing: string | null

  load: () => Promise<void>
  completeStep: (step: OnboardingStepId, payload?: StepPayload) => Promise<void>
  createWorkspace: (name: string, description: string) => Promise<string | null>
  setTheme: (theme: ThemeChoice) => Promise<void>
  setTelemetry: (mode: 'disabled' | 'crash_only' | 'diagnostics') => Promise<void>
  installDemo: (demoId: string) => Promise<DemoInstallResult | null>
  skip: () => Promise<void>
  reset: () => Promise<void>
  clearError: () => void
}

function message(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return 'Something went wrong.'
}

export const useOnboardingStore = create<OnboardingStore>((set, get) => ({
  state: null,
  demos: [],
  installed: {},
  phase: 'idle',
  error: null,
  installing: null,

  async load() {
    set({ phase: 'loading', error: null })
    try {
      const [state, demos] = await Promise.all([
        onboardingService.state(),
        // A failed demo catalogue must not block setup — the picker simply
        // shows nothing rather than trapping the user on a broken screen.
        onboardingService.demos().catch(() => [] as DemoSummary[]),
      ])
      set({ state, demos, phase: 'ready' })
    } catch {
      // No kernel to ask. Treat setup as done so the application still opens;
      // a browser running against mock data has nothing to set up.
      set({ state: ASSUMED_COMPLETE, demos: [], phase: 'ready' })
    }
  },

  async completeStep(step, payload = {}) {
    set({ phase: 'working', error: null })
    try {
      const state = await onboardingService.completeStep(step, payload)
      set({ state, phase: 'ready' })
    } catch (error) {
      set({ phase: 'ready', error: message(error) })
    }
  },

  async createWorkspace(name, description) {
    set({ phase: 'working', error: null })
    try {
      const { workspace_id } = await onboardingService.createWorkspace(name, description)
      const state = await onboardingService.completeStep('workspace', {
        workspace_id,
        workspace_name: name,
      })
      set({ state, phase: 'ready' })
      return workspace_id
    } catch (error) {
      set({ phase: 'ready', error: message(error) })
      return null
    }
  },

  async setTheme(theme) {
    // Applied immediately so the choice is visible while still on the screen
    // that offers it, then recorded.
    applyTheme(theme)
    await get().completeStep('theme', { theme })
  },

  async setTelemetry(mode) {
    set({ phase: 'working', error: null })
    try {
      await onboardingService.setTelemetry(mode)
      const state = await onboardingService.completeStep('diagnostics')
      set({ state, phase: 'ready' })
    } catch (error) {
      set({ phase: 'ready', error: message(error) })
    }
  },

  async installDemo(demoId) {
    set({ installing: demoId, error: null })
    try {
      const result = await onboardingService.installDemo(demoId)
      set((current) => ({
        installed: { ...current.installed, [demoId]: result },
        installing: null,
      }))
      return result
    } catch (error) {
      set({ installing: null, error: message(error) })
      return null
    }
  },

  async skip() {
    set({ phase: 'working', error: null })
    try {
      const state = await onboardingService.skip()
      set({ state, phase: 'ready' })
    } catch (error) {
      set({ phase: 'ready', error: message(error) })
    }
  },

  async reset() {
    set({ phase: 'working', error: null })
    try {
      const state = await onboardingService.reset()
      set({ state, phase: 'ready', installed: {} })
    } catch (error) {
      set({ phase: 'ready', error: message(error) })
    }
  },

  clearError() {
    set({ error: null })
  },
}))

/**
 * Put the chosen theme on the document.
 *
 * `system` follows the OS rather than freezing whatever it happens to be right
 * now, so a machine that switches at sunset takes Atlas with it.
 */
export function applyTheme(theme: ThemeChoice): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  const resolved =
    theme === 'system'
      ? window.matchMedia('(prefers-color-scheme: light)').matches
        ? 'light'
        : 'dark'
      : theme
  root.dataset.theme = resolved
  root.style.colorScheme = resolved
}
