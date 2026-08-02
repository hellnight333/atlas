import { NavLink } from 'react-router-dom'

import { cn } from '../utils/cn'

type SidebarItemProps = {
  to: string
  label: string
}

export function SidebarItem({ to, label }: SidebarItemProps) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          'rounded px-3 py-2 text-left text-sm transition',
          isActive ? 'bg-cyan-500/20 text-cyan-200 ring-1 ring-cyan-500/40' : 'text-slate-300 hover:bg-slate-800',
        )
      }
    >
      {label}
    </NavLink>
  )
}
