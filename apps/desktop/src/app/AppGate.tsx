import { useCallback, useEffect, useState } from 'react'

import { isDesktopShell } from '../api/runtime'
import { BootScreen } from '../features/onboarding/BootScreen'
import { OnboardingFlow } from '../features/onboarding/OnboardingFlow'
import { applyTheme, useOnboardingStore } from '../stores/onboardingStore'
import { App } from './App'

/**
 * What the user sees before the application proper.
 *
 * Three phases, in order:
 *
 *  1. **Booting** — only in the packaged shell, where Atlas is starting its own
 *     database and kernel. In a browser the kernel is someone else's problem
 *     and this phase is skipped entirely.
 *  2. **Setup** — the first run, once per installation.
 *  3. **Atlas.**
 *
 * The gate is deliberately fail-open. If the kernel cannot be reached, setup
 * state is assumed complete and the application opens anyway: a user who
 * cannot get past a setup screen has no way to diagnose why, whereas the app
 * itself has a diagnostics screen that can explain it.
 */
export function AppGate() {
  const [booted, setBooted] = useState(() => !isDesktopShell())
  const { state, load, phase } = useOnboardingStore()

  const handleReady = useCallback(() => setBooted(true), [])

  useEffect(() => {
    // Asking before the kernel is up would fail and be assumed complete,
    // skipping setup on every first run in the packaged app.
    if (booted) void load()
  }, [booted, load])

  useEffect(() => {
    if (state?.theme) applyTheme(state.theme)
  }, [state?.theme])

  if (!booted) {
    return <BootScreen onReady={handleReady} />
  }

  if (phase === 'idle' || phase === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <span
          className="h-5 w-5 animate-spin rounded-full border-2 border-slate-700 border-t-cyan-400"
          role="status"
          aria-label="Loading Atlas"
        />
      </div>
    )
  }

  if (state && !state.completed) {
    return <OnboardingFlow onDone={() => void load()} />
  }

  return <App />
}
