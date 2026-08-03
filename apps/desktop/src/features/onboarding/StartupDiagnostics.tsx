import { useCallback, useState } from 'react'

import {
  diagnosticReport,
  openLogFolder,
  resetDatabase,
  retryBootstrap,
  startupLog,
} from '../../api/shell'

/**
 * What Atlas shows instead of a blank window when it cannot start.
 *
 * RC1 could reach "Waiting for the kernel to come up" and then render nothing
 * at all, forever, with no error and no way to find out why. A user in that
 * state has no shell, no logs they know how to find, and nothing to send. This
 * screen is the floor: it always names a reason, and it always offers a way to
 * get the evidence out of the machine.
 */

type Props = {
  /** Why the boot did not finish. Always shown; never left blank. */
  reason: string
  /** The stage reached before giving up, if one was reported. */
  stage?: string
  /**
   * What Retry should do. Defaults to restarting the boot sequence, which is
   * right when the shell failed — but wrong when the shell is fine and the UI
   * crashed, where reloading the window is the recovery.
   */
  onRetry?: () => void | Promise<void>
  retryLabel?: string
}

type Copied = 'idle' | 'copied' | 'failed'

export function StartupDiagnostics({ reason, stage, onRetry, retryLabel = 'Retry' }: Props) {
  const [log, setLog] = useState<string | null>(null)
  const [showLog, setShowLog] = useState(false)
  const [copied, setCopied] = useState<Copied>('idle')
  const [retrying, setRetrying] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [confirmingReset, setConfirmingReset] = useState(false)

  // Offered only when the database is the thing that is broken. A reset button
  // shown for a network error would be an invitation to destroy data over a
  // problem it cannot fix.
  const databaseIsDamaged =
    /damaged beyond repair|checkpoint record|different database system|incompatible with server|control file/i.test(
      reason,
    )

  const doReset = useCallback(async () => {
    setActionError(null)
    try {
      const archived = await resetDatabase()
      setActionError(`Old database kept at ${archived}. Atlas is starting over.`)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error))
    }
  }, [])

  const viewLogs = useCallback(async () => {
    setShowLog(true)
    setLog(await startupLog(400))
  }, [])

  const copyReport = useCallback(async () => {
    const report = await diagnosticReport()
    try {
      await navigator.clipboard.writeText(report)
      setCopied('copied')
    } catch {
      // The webview can refuse clipboard access. Showing the report is still
      // better than telling the user it could not be copied and stopping.
      setLog(report)
      setShowLog(true)
      setCopied('failed')
    }
  }, [])

  const openDiagnostics = useCallback(async () => {
    setActionError(null)
    try {
      await openLogFolder()
    } catch (error) {
      setActionError(
        `Could not open the log folder: ${error instanceof Error ? error.message : String(error)}`,
      )
    }
  }, [])

  const retry = useCallback(async () => {
    setActionError(null)
    setRetrying(true)
    try {
      await (onRetry ? onRetry() : retryBootstrap())
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error))
      setRetrying(false)
    }
  }, [onRetry])

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-6 py-10">
      <div className="w-full max-w-xl">
        <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl border border-rose-500/40 bg-rose-500/10">
          <div className="h-4 w-4 rounded-full bg-rose-400" aria-hidden />
        </div>

        <h1 className="text-center text-lg font-medium text-slate-100">Atlas could not start.</h1>

        <div
          role="alert"
          className="mt-5 rounded-lg border border-rose-500/30 bg-rose-500/5 p-4 text-sm leading-relaxed text-rose-100"
        >
          {reason}
          {stage && <span className="mt-2 block text-xs text-rose-300/80">Last stage: {stage}</span>}
        </div>

        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <button
            type="button"
            onClick={() => void retry()}
            disabled={retrying}
            className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-400 disabled:opacity-60"
          >
            {retrying ? 'Retrying…' : retryLabel}
          </button>
          <button
            type="button"
            onClick={() => void openDiagnostics()}
            className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 transition hover:border-slate-500"
          >
            Open diagnostics
          </button>
          <button
            type="button"
            onClick={() => void viewLogs()}
            className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 transition hover:border-slate-500"
          >
            View logs
          </button>
          {databaseIsDamaged && (
            <button
              type="button"
              onClick={() => (confirmingReset ? void doReset() : setConfirmingReset(true))}
              className={
                'rounded-md px-4 py-2 text-sm font-medium transition ' +
                (confirmingReset
                  ? 'bg-rose-500 text-white hover:bg-rose-400'
                  : 'border border-rose-500/50 text-rose-200 hover:border-rose-400')
              }
            >
              {confirmingReset ? 'Yes — start with a new database' : 'Reset the database'}
            </button>
          )}
          <button
            type="button"
            onClick={() => void copyReport()}
            className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 transition hover:border-slate-500"
          >
            {copied === 'copied' ? 'Report copied' : 'Copy diagnostic report'}
          </button>
        </div>

        {copied === 'failed' && (
          <p className="mt-3 text-center text-xs text-amber-300/90">
            The clipboard was not available, so the report is shown below instead.
          </p>
        )}

        {confirmingReset && (
          <p className="mt-3 text-center text-xs text-rose-300">
            This starts Atlas over with an empty database. The damaged one is kept, renamed,
            in the same folder — nothing is deleted.
          </p>
        )}

        {actionError && (
          <p className="mt-3 text-center text-xs text-rose-300">{actionError}</p>
        )}

        {showLog && (
          <pre className="mt-5 max-h-80 overflow-auto rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-[11px] leading-relaxed text-slate-400">
            {log ?? 'No log has been written yet.'}
          </pre>
        )}

        <p className="mt-6 text-center text-xs text-slate-500">
          Logs are written to the <code className="text-slate-400">logs</code> folder in the Atlas
          data directory. Quitting and reopening Atlas clears anything a previous crash left
          running.
        </p>
      </div>
    </div>
  )
}
