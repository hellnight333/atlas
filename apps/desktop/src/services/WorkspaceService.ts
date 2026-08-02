import { getAtlasProvider } from '../providers/ProviderContext'
import type { Studio } from '../types/domain'

export interface WorkspaceService {
  listStudios(): Promise<Studio[]>
  getStudioById(id: string): Promise<Studio | undefined>
}

export const workspaceService: WorkspaceService = {
  async listStudios() {
    return getAtlasProvider().getStudios()
  },
  async getStudioById(id) {
    const studios = await getAtlasProvider().getStudios()
    return studios.find((studio) => studio.id === id)
  },
}
