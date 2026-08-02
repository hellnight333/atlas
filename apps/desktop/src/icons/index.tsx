import type { ReactNode } from 'react'

type IconProps = {
  children: ReactNode
}

function IconFrame({ children }: IconProps) {
  return <span className="inline-flex h-4 w-4 items-center justify-center text-current">{children}</span>
}

export function GridIcon() {
  return <IconFrame>□</IconFrame>
}

export function SparkIcon() {
  return <IconFrame>✦</IconFrame>
}

export function SearchIcon() {
  return <IconFrame>⌕</IconFrame>
}

export function ActivityIcon() {
  return <IconFrame>◔</IconFrame>
}

export function AlertIcon() {
  return <IconFrame>!</IconFrame>
}
