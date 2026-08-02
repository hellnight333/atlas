import type { ReactNode } from 'react'

export function Window({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">{children}</div>
}
