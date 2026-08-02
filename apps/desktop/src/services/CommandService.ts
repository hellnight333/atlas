import { getAtlasProvider } from '../providers/ProviderContext'
import type { CommandItem } from '../types/domain'

export interface CommandService {
  list(): Promise<CommandItem[]>
}

export const commandService: CommandService = {
  async list() {
    return getAtlasProvider().getCommands()
  },
}
