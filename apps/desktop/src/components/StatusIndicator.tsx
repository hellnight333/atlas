import type { Severity } from '../types/domain'
import { cn } from '../utils/cn'

const severityClass: Record<Severity, string> = {
  info: 'bg-sky-500/15 text-sky-300 border-sky-400/40',
  attention: 'bg-indigo-500/15 text-indigo-300 border-indigo-400/40',
  warning: 'bg-amber-500/15 text-amber-300 border-amber-400/40',
  critical: 'bg-rose-600/20 text-rose-200 border-rose-400/60',
}

export function StatusIndicator({ severity, label }: { severity: Severity; label: string }) {
  return <span className={cn('rounded border px-2 py-0.5 text-xs capitalize', severityClass[severity])}>{label}</span>
}
