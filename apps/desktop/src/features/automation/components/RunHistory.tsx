import type { AutomationRun } from '../../../api/types'

const STATUS_STYLES: Record<string, string> = {
  completed: 'text-emerald-300',
  failed: 'text-rose-300',
  skipped: 'text-amber-300',
  running: 'text-cyan-300',
  pending: 'text-slate-400',
}

export function RunHistory({ runs }: { runs: AutomationRun[] }) {
  if (runs.length === 0) {
    return <p className="text-sm text-slate-500">No runs recorded yet.</p>
  }

  return (
    <ul className="space-y-2">
      {runs.map((run) => (
        <li key={run.id} className="rounded bg-slate-900 px-3 py-2 text-sm">
          <div className="flex items-center justify-between gap-2">
            <span className={`text-xs uppercase tracking-widest ${STATUS_STYLES[run.status] ?? 'text-slate-400'}`}>
              {run.status}
            </span>
            <span className="text-xs text-slate-500">
              {run.duration_ms != null ? `${run.duration_ms}ms` : '—'}
            </span>
          </div>
          <p className="mt-1 text-slate-300">Triggered by {run.triggered_by}</p>
          <p className="text-xs text-slate-500">
            {new Date(run.start_time).toLocaleString()}
            {run.retries > 0 ? ` · ${run.retries} retr${run.retries === 1 ? 'y' : 'ies'}` : ''}
          </p>
          {run.error ? <p className="mt-1 text-xs text-rose-300">{run.error}</p> : null}
          {typeof run.outputs.skip_reason === 'string' ? (
            <p className="mt-1 text-xs text-amber-300">Skipped: {run.outputs.skip_reason}</p>
          ) : null}
        </li>
      ))}
    </ul>
  )
}
