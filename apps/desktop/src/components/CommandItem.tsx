import type { CommandItem as Command } from '../types/domain'

export function CommandItem({ command, onSelect }: { command: Command; onSelect: (id: string) => void }) {
  return (
    <button
      type="button"
      className="block w-full rounded border border-slate-700 bg-slate-950 px-2 py-2 text-left text-sm hover:border-slate-500"
      onClick={() => onSelect(command.id)}
    >
      <p>{command.label}</p>
      <p className="text-xs text-slate-500">
        {command.kind} · {command.scope}
      </p>
    </button>
  )
}
