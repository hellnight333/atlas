import type { ReactNode } from 'react'

export function Toolbar({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 bg-slate-900 px-4 py-3">{children}</div>
}
