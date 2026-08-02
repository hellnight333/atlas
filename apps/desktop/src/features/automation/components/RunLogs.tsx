import type { AutomationLog } from '../../../api/types'

const LEVEL_STYLES: Record<string, string> = {
  error: 'text-rose-300',
  warning: 'text-amber-300',
  info: 'text-slate-400',
  debug: 'text-slate-500',
}

export function RunLogs({ logs }: { logs: AutomationLog[] }) {
  if (logs.length === 0) {
    return <p className="text-sm text-slate-500">No logs recorded yet.</p>
  }

  return (
    <ul className="space-y-2">
      {logs.map((log) => (
        <li key={log.id} className="rounded bg-slate-900 px-3 py-2 text-sm">
          <div className="flex items-center justify-between gap-2">
            <span className={`text-xs uppercase tracking-widest ${LEVEL_STYLES[log.level] ?? 'text-slate-400'}`}>
              {log.level}
            </span>
            <span className="text-xs text-slate-500">{log.actor}</span>
          </div>
          <p className="mt-1 text-slate-200">{log.message}</p>
          <p className="text-xs text-slate-500">{new Date(log.created_at).toLocaleString()}</p>
        </li>
      ))}
    </ul>
  )
}
