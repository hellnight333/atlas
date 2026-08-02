import type { CommandMode } from './domain'

export type RouteScreen =
  | 'desktop-overview'
  | 'workspace'
  | 'project'
  | 'asset'
  | 'studio'
  | 'research'
  | 'mission-control'
  | 'activity-center'

export type NavigationItem = {
  label: string
  to: string
  screen: RouteScreen
}

export type OverlayState = {
  missionControlOpen: boolean
  commandPaletteOpen: boolean
  activityCenterOpen: boolean
}

export type CommandPaletteState = {
  mode: CommandMode
  query: string
}
