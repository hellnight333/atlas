import type { ReactNode } from 'react'

import { cn } from '../utils/cn'

type PanelProps = {
  title: string
  subtitle?: string
  children?: ReactNode
  className?: string
}

export function Panel({ title, subtitle, children, className }: PanelProps) {
  return (
    <section className={cn('rounded-lg border border-slate-700 bg-slate-950 p-4 shadow-sm', className)}>
      <h3 className="text-base font-semibold text-slate-100">{title}</h3>
      {subtitle ? <p className="mt-1 text-sm text-slate-400">{subtitle}</p> : null}
      {children ? <div className="mt-3">{children}</div> : null}
    </section>
  )
}
