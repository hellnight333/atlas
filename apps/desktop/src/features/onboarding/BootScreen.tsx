import { useEffect, useState } from 'react'

import {
  BROWSER_PROGRESS,
  INITIAL_PROGRESS,
  databaseLog,
  onBootstrapProgress,
  type BootstrapProgress,
  type BootstrapStage,
} from '../../api/shell'
import { isDesktopShell } from '../../api/runtime'

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
  const [log, setLog] = useState<string | null>(null)
  const [showDetail, setShowDetail] = useState(false)

  useEffect(() => {
    let cancelled = false
    let unsubscribe: (() => void) | undefined

    onBootstrapProgress((next) => {
      if (cancelled) return
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

  const failed = progress.stage === 'failed'
  const percent = failed ? 100 : Math.round((stageIndex(progress.stage) / (STAGE_ORDER.length - 1)) * 100)

  async function loadLog() {
    setShowDetail(true)
    setLog(await databaseLog(120))
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-6">
      <div className="w-full max-w-md text-center">
        <div
          className={
            'mx-auto mb-8 flex h-16 w-16 items-center justify-center rounded-2xl border ' +
            (failed
              ? 'border-rose-500/40 bg-rose-500/10'
              : 'border-slate-700 bg-slate-900')
          }
        >
          <div
            className={
              'h-4 w-4 rounded-full ' +
              (failed ? 'bg-rose-400' : 'animate-pulse bg-cyan-300')
            }
            aria-hidden
          />
        </div>

        <h1 className="text-lg font-medium text-slate-100">
          {failed ? 'Atlas could not start' : progress.message}
        </h1>

        {progress.first_run && !failed && (
          <p className="mt-2 text-sm text-slate-400">
            Setting things up for the first time. This happens once.
          </p>
        )}

        {progress.detail && !failed && !progress.first_run && (
          <p className="mt-2 truncate text-xs text-slate-500" title={progress.detail}>
            {progress.detail}
          </p>
        )}

        {!failed && (
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
        )}

        {failed && (
          <div className="mt-6 space-y-4 text-left">
            <div
              role="alert"
              className="rounded-lg border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200"
            >
              {progress.detail ?? 'The reason was not reported.'}
            </div>

            <div className="flex gap-2">
              <button
                type="button"
                onClick={loadLog}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 transition hover:border-slate-500"
              >
                Show database log
              </button>
            </div>

            {showDetail && (
              <pre className="max-h-56 overflow-auto rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-[11px] leading-relaxed text-slate-400">
                {log ?? 'No log has been written yet.'}
              </pre>
            )}

            <p className="text-xs text-slate-500">
              Quitting and reopening Atlas clears anything a previous crash left running.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
