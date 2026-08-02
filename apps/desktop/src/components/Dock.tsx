import type { ReactNode } from 'react'

export function Dock({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-t border-slate-800 bg-slate-900/80 px-4 py-3">
      <div className="mb-2 flex items-center justify-between text-xs uppercase tracking-widest text-slate-400">
        <span>{title}</span>
        {action}
      </div>
      {children}
    </section>
  )
}
