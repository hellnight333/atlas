import type { ReactNode } from 'react'

export function WorkspaceHeader({ title, subtitle, actions }: { title: string; subtitle: string; actions?: ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900 px-4 py-3">
      <div>
        <h1 className="text-lg font-semibold text-slate-100">{title}</h1>
        <p className="text-sm text-slate-400">{subtitle}</p>
      </div>
      {actions ? <div className="flex items-center gap-2 text-xs text-slate-400">{actions}</div> : null}
    </div>
  )
}
