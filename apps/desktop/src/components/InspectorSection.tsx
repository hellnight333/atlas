import type { ReactNode } from 'react'

export function InspectorSection({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-700 bg-slate-950 p-3">
      <h4 className="text-sm font-semibold text-slate-100">{title}</h4>
      {children ? <div className="mt-2 text-sm text-slate-300">{children}</div> : null}
    </section>
  )
}
