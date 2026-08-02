import type { ButtonHTMLAttributes, ReactNode } from 'react'

import { cn } from '../utils/cn'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'accent' | 'ghost'
  children: ReactNode
}

export function Button({ variant = 'default', className, children, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        'rounded-md border px-3 py-1.5 text-sm transition',
        variant === 'default' && 'border-slate-700 bg-slate-900 text-slate-200 hover:border-slate-500',
        variant === 'accent' && 'border-cyan-500/50 bg-cyan-500/15 text-cyan-200 hover:border-cyan-400',
        variant === 'ghost' && 'border-transparent bg-transparent text-slate-300 hover:bg-slate-800',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}
