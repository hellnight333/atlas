import { useEffect, useState } from 'react'

import {
  BROWSER_PROGRESS,
  INITIAL_PROGRESS,
  logStartup,
  onBootstrapProgress,
  type BootstrapProgress,
  type BootstrapStage,
} from '../../api/shell'
import { isDesktopShell } from '../../api/runtime'
import { StartupDiagnostics } from './StartupDiagnostics'

/**
 * How long Atlas may sit on the splash before it owes the user an explanation.
 *
 * The shell gives the kernel 90 seconds, deliberately — a first run on a cold
 * machine really can take that long. But the user must not be looking at a
 * silent window for 90 seconds to find that out, so the UI stops waiting well
 * before the shell does and offers diagnostics instead.
 */
const BOOT_DEADLINE_MS = 30_000

/**
 * What the user looks at while Atlas starts itself.
 *
 * A first launch does real work — creating a database cluster takes several
 * seconds — and an unexplained blank window reads as a hang. Each stage is
 * named, and the first run says plainly that it only happens once.
 */

const STAGE_ORDER: BootstrapStage[] = [
  'starting',
  'preparing_storage',
  'initialising_database',
  'starting_database',
  'starting_kernel',
  'waiting_for_kernel',
  'ready',
]

function stageIndex(stage: BootstrapStage): number {
  const index = STAGE_ORDER.indexOf(stage)
  return index < 0 ? 0 : index
}

export function BootScreen({ onReady }: { onReady: () => void }) {
  const [progress, setProgress] = useState<BootstrapProgress>(
    isDesktopShell() ? INITIAL_PROGRESS : BROWSER_PROGRESS,
  )
  const [timedOut, setTimedOut] = useState(false)

  useEffect(() => {
    let cancelled = false
    let unsubscribe: (() => void) | undefined

    logStartup('boot screen mounted')

    onBootstrapProgress((next) => {
      if (cancelled) return
      logStartup(`bootstrap event: ${next.stage} — ${next.message}`)
      setProgress(next)
      if (next.stage === 'ready') onReady()
    }).then((fn) => {
      if (cancelled) fn()
      else unsubscribe = fn
    })

    return () => {
      cancelled = true
      unsubscribe?.()
    }
  }, [onReady])

  // Stop waiting after the deadline, whatever the shell is still doing.
  useEffect(() => {
    if (progress.stage === 'ready' || progress.stage === 'failed') return
    const timer = setTimeout(() => {
      logStartup(`boot deadline reached while at stage ${progress.stage}`)
      setTimedOut(true)
    }, BOOT_DEADLINE_MS)
    return () => clearTimeout(timer)
  }, [progress.stage])

  const failed = progress.stage === 'failed'

  if (failed || timedOut) {
    return (
      <StartupDiagnostics
        stage={progress.message}
        reason={
          failed
            ? (progress.detail ??
              'The shell reported a failure but did not say what went wrong. The startup log below has the sequence it managed to complete.')
            : `Atlas did not finish starting within ${BOOT_DEADLINE_MS / 1000} seconds. It was still at "${progress.message}".`
        }
      />
    )
  }

  const percent = Math.round((stageIndex(progress.stage) / (STAGE_ORDER.length - 1)) * 100)

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-6">
      <div className="w-full max-w-md text-center">
        <div className="mx-auto mb-8 flex h-16 w-16 items-center justify-center rounded-2xl border border-slate-700 bg-slate-900">
          <div className="h-4 w-4 animate-pulse rounded-full bg-cyan-300" aria-hidden />
        </div>

        <h1 className="text-lg font-medium text-slate-100">{progress.message}</h1>

        {progress.first_run && (
          <p className="mt-2 text-sm text-slate-400">
            Setting things up for the first time. This happens once.
          </p>
        )}

        {progress.detail && !progress.first_run && (
          <p className="mt-2 truncate text-xs text-slate-500" title={progress.detail}>
            {progress.detail}
          </p>
        )}

        <div
          className="mt-8 h-1 w-full overflow-hidden rounded-full bg-slate-800"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Startup progress"
        >
          <div
            className="h-full rounded-full bg-cyan-400 transition-all duration-500 ease-out"
            style={{ width: `${percent}%` }}
          />
        </div>
      </div>
    </div>
  )
}
