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
 * How long any single stage may take before the UI gives up on it.
 *
 * Per stage, not per boot: a boot that is still advancing is not stuck, and
 * timing the whole thing punishes a slow machine for being slow. The timer
 * resets whenever the stage changes.
 *
 * It was 30s, which was too tight and produced a *false* failure screen on a
 * first run under Rosetta — `initdb` and a cold kernel import are each easily
 * that long when every instruction is being translated. The shell reports a
 * real failure of its own at 90s, so this only has to be long enough that the
 * shell always gets to speak first; when it does, the user sees the actual
 * reason rather than "it took too long".
 */
const STAGE_DEADLINE_MS = 120_000

/** When to admit it is taking a while, rather than looking frozen. */
const SLOW_AFTER_MS = 20_000

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
  const [slow, setSlow] = useState(false)
  const [seconds, setSeconds] = useState(0)

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

  // Give up only if a single stage stops making progress. Resets on every
  // stage change, so a slow boot is allowed to be slow.
  useEffect(() => {
    if (progress.stage === 'ready' || progress.stage === 'failed') return
    const timer = setTimeout(() => {
      logStartup(`stage ${progress.stage} exceeded ${STAGE_DEADLINE_MS / 1000}s`)
      setTimedOut(true)
    }, STAGE_DEADLINE_MS)
    return () => clearTimeout(timer)
  }, [progress.stage])

  // A progress bar that has not moved for twenty seconds reads as frozen even
  // when it is working. Saying so, with a count, is the difference between
  // waiting and wondering whether to force-quit.
  useEffect(() => {
    setSlow(false)
    setSeconds(0)
    if (progress.stage === 'ready' || progress.stage === 'failed') return
    const started = Date.now()
    const tick = setInterval(() => {
      const elapsed = Math.round((Date.now() - started) / 1000)
      setSeconds(elapsed)
      if (elapsed * 1000 >= SLOW_AFTER_MS) setSlow(true)
    }, 1000)
    return () => clearInterval(tick)
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
            : `Atlas stopped making progress at "${progress.message}" and has been ` +
              `there for over ${STAGE_DEADLINE_MS / 1000} seconds. The startup log below ` +
              `shows every step it did complete.`
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

        {slow && (
          <p className="mt-2 text-sm text-amber-300/80">
            Still working — {seconds}s so far. A first run, or a translated build on Apple
            Silicon, is slower.
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
