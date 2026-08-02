import type { WorkerNode } from '../../../api/types'
import { WORKER_STATUS_STYLES } from '../constants'

export function WorkerCard({
  worker,
  selected,
  onSelect,
}: {
  worker: WorkerNode
  selected: boolean
  onSelect: () => void
}) {
  const ratio = worker.max_concurrency ? worker.current_load / worker.max_concurrency : 0

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`block w-full rounded border px-3 py-2 text-left ${
        selected
          ? 'border-cyan-500/50 bg-cyan-500/10'
          : 'border-slate-800 bg-slate-900 hover:bg-slate-800'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-slate-100">{worker.display_name}</span>
        <span
          className={`text-xs uppercase tracking-widest ${WORKER_STATUS_STYLES[worker.status] ?? 'text-slate-400'}`}
        >
          {worker.status}
        </span>
      </div>

      <div className="mt-2 h-1 overflow-hidden rounded bg-slate-800">
        <div
          className={`h-full ${ratio >= 1 ? 'bg-amber-400' : 'bg-cyan-400'}`}
          style={{ width: `${Math.min(100, Math.round(ratio * 100))}%` }}
        />
      </div>

      <p className="mt-1.5 text-xs text-slate-500">
        {worker.current_load}/{worker.max_concurrency} slots
        {worker.resources.gpu ? ` · ${worker.resources.gpu} ${worker.resources.vram_gb}GB` : ''}
      </p>
      <p className="text-xs text-slate-500">{worker.capabilities.join(', ') || 'no capabilities'}</p>
      {worker.tags.length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-1">
          {worker.tags.map((tag) => (
            <span key={tag} className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
              {tag}
            </span>
          ))}
        </div>
      ) : null}
    </button>
  )
}
