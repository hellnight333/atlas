import { useNavigate } from 'react-router-dom'
import { useMemo } from 'react'

import { Button, CommandItem, SearchBar, Window } from '../../../components'
import {
  useCommandPaletteStore,
  useMissionControlStore,
  useUIStore,
  useWorkspaceStore,
} from '../../../stores'
import type { CommandMode } from '../../../types/domain'

export function CommandPaletteOverlay() {
  const navigate = useNavigate()
  const open = useCommandPaletteStore((state) => state.open)
  const mode = useCommandPaletteStore((state) => state.mode)
  const query = useCommandPaletteStore((state) => state.query)
  const commands = useCommandPaletteStore((state) => state.commands)
  const recentCommandIds = useCommandPaletteStore((state) => state.recentCommandIds)
  const pinnedCommandIds = useCommandPaletteStore((state) => state.pinnedCommandIds)
  const setOpen = useCommandPaletteStore((state) => state.setOpen)
  const setMode = useCommandPaletteStore((state) => state.setMode)
  const setQuery = useCommandPaletteStore((state) => state.setQuery)
  const pushRecent = useCommandPaletteStore((state) => state.pushRecent)
  const setMissionOpen = useMissionControlStore((state) => state.setOpen)
  const setActivityCenterOpen = useUIStore((state) => state.setActivityCenterOpen)
  const setSelectedStudioId = useWorkspaceStore((state) => state.setSelectedStudioId)

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) {
      return commands
    }
    return commands.filter((command) => command.label.toLowerCase().includes(normalized))
  }, [commands, query])

  const recentCommands = commands.filter((command) => recentCommandIds.includes(command.id))
  const pinnedCommands = commands.filter((command) => pinnedCommandIds.includes(command.id))

  if (!open) {
    return null
  }

  const handleSelect = (commandId: string) => {
    pushRecent(commandId)
    setOpen(false)
    setQuery('')

    switch (commandId) {
      case 'c1':
        setMissionOpen(true)
        navigate('/mission-control')
        break
      case 'c2':
        setSelectedStudioId('s1')
        navigate('/studio/s1')
        break
      case 'c3':
        setActivityCenterOpen(true)
        navigate('/activity-center')
        break
      default:
        break
    }
  }

  return (
    <section className="fixed inset-0 z-50 flex items-start justify-center bg-slate-950/60 p-6 backdrop-blur-sm">
      <Window>
        <div className="w-full max-w-4xl">
          <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
            <h2 className="text-sm font-semibold">Command Palette</h2>
            <Button onClick={() => setOpen(false)}>Close</Button>
          </div>
          <div className="border-b border-slate-700 px-4 py-3">
            <div className="mb-3 flex flex-wrap gap-2">
              {(['command', 'search', 'quick-action', 'ai'] as CommandMode[]).map((candidateMode) => (
                <Button
                  key={candidateMode}
                  variant={mode === candidateMode ? 'accent' : 'default'}
                  onClick={() => setMode(candidateMode)}
                >
                  {candidateMode}
                </Button>
              ))}
            </div>
            <SearchBar
              value={query}
              onChange={setQuery}
              placeholder="Type command, search query, or natural language intent"
            />
          </div>
          <div className="grid gap-4 p-4 md:grid-cols-3">
            <div>
              <h3 className="mb-2 text-xs uppercase tracking-widest text-slate-500">Candidates</h3>
              <div className="space-y-1">
                {filtered.map((command) => (
                  <CommandItem key={command.id} command={command} onSelect={handleSelect} />
                ))}
              </div>
            </div>
            <div>
              <h3 className="mb-2 text-xs uppercase tracking-widest text-slate-500">Recent Commands</h3>
              <div className="space-y-1">
                {recentCommands.map((command) => (
                  <CommandItem key={command.id} command={command} onSelect={handleSelect} />
                ))}
              </div>
            </div>
            <div>
              <h3 className="mb-2 text-xs uppercase tracking-widest text-slate-500">Pinned Commands</h3>
              <div className="space-y-1">
                {pinnedCommands.map((command) => (
                  <CommandItem key={command.id} command={command} onSelect={handleSelect} />
                ))}
              </div>
              <div className="mt-2 rounded border border-slate-700 bg-slate-950 p-2 text-xs text-slate-400">
                TODO: Final command alias precedence across plugin namespaces remains deferred.
              </div>
            </div>
          </div>
        </div>
      </Window>
    </section>
  )
}
