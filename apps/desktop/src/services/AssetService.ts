import type { AssetImportRequest } from '../api/types'
import { getAtlasProvider } from '../providers/ProviderContext'
import type { Asset } from '../types/domain'

export interface AssetService {
  list(): Promise<Asset[]>
  listByProject(projectId: string): Promise<Asset[]>
  getById(id: string): Promise<Asset | undefined>
  importAsset(request: AssetImportRequest): Promise<Asset>
  deleteAsset(id: string): Promise<void>
}

export const assetService: AssetService = {
  async list() {
    return getAtlasProvider().getAssets()
  },
  async listByProject(projectId) {
    return getAtlasProvider().getProjectAssets(projectId)
  },
  async getById(id) {
    return getAtlasProvider().getAsset(id)
  },
  async importAsset(request) {
    return getAtlasProvider().importAsset(request)
  },
  async deleteAsset(id) {
    return getAtlasProvider().deleteAsset(id)
  },
}
