import { useCallback, useEffect, useState } from 'react'

import { isDesktopShell } from '../api/runtime'
import { logStartup } from '../api/shell'
import { BootScreen } from '../features/onboarding/BootScreen'
import { OnboardingFlow } from '../features/onboarding/OnboardingFlow'
import { StartupDiagnostics } from '../features/onboarding/StartupDiagnostics'
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
 *
 * Fail-open only works if the attempt actually finishes. Every phase here is
 * bounded, because the one failure this gate must never produce again is the
 * one RC1 shipped: a window that renders nothing, forever, with no error.
 */

/** How long the post-boot load may take before the user gets an explanation. */
const LOAD_DEADLINE_MS = 30_000

export function AppGate() {
  const [booted, setBooted] = useState(() => !isDesktopShell())
  const [stalled, setStalled] = useState(false)
  const { state, load, phase } = useOnboardingStore()

  const handleReady = useCallback(() => setBooted(true), [])

  useEffect(() => {
    // Asking before the kernel is up would fail and be assumed complete,
    // skipping setup on every first run in the packaged app.
    if (booted) {
      logStartup('kernel ready; loading setup state')
      void load()
    }
  }, [booted, load])

  // The store's own failure path is fail-open, so reaching this timer means a
  // request neither resolved nor rejected. That is a bug worth surfacing
  // rather than hiding behind a spinner.
  useEffect(() => {
    if (!booted) return
    if (phase !== 'idle' && phase !== 'loading') return
    const timer = setTimeout(() => {
      logStartup(`setup state did not load within ${LOAD_DEADLINE_MS / 1000}s (phase=${phase})`)
      setStalled(true)
    }, LOAD_DEADLINE_MS)
    return () => clearTimeout(timer)
  }, [booted, phase])

  useEffect(() => {
    if (state?.theme) applyTheme(state.theme)
  }, [state?.theme])

  useEffect(() => {
    if (phase === 'ready') logStartup('setup state loaded')
  }, [phase])

  if (!booted) {
    return <BootScreen onReady={handleReady} />
  }

  if (stalled) {
    return (
      <StartupDiagnostics
        stage="Loading setup state"
        reason={`The Atlas kernel reported that it was ready, but it did not answer a request within ${
          LOAD_DEADLINE_MS / 1000
        } seconds. The kernel may have started and then stopped; logs/kernel.log will say.`}
      />
    )
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
    logStartup('rendering first-run setup')
    return <OnboardingFlow onDone={() => void load()} />
  }

  logStartup('rendering main application')
  return <App />
}
