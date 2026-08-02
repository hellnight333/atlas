import { create } from 'zustand'

import type { AssetImportRequest, ResourceState } from '../api/types'
import { assetService } from '../services/AssetService'
import { toApiError } from '../services/types'
import type { ApiError, ApiStatus } from '../api/types'
import type { Asset } from '../types/domain'

type AssetStore = {
  assets: Asset[]
  projectAssets: Record<string, ResourceState<Asset[]>>
  selectedAssetId: string
  status: ApiStatus
  error: ApiError | null
  lastLoadedAt: number | null
  loadAssets: () => Promise<void>
  refreshAssets: () => Promise<void>
  loadProjectAssets: (projectId: string) => Promise<void>
  importAsset: (request: AssetImportRequest) => Promise<void>
  deleteAsset: (assetId: string) => Promise<void>
  setSelectedAssetId: (assetId: string) => void
}

export const useAssetStore = create<AssetStore>((set) => ({
  assets: [],
  projectAssets: {},
  selectedAssetId: 'a1',
  status: 'idle',
  error: null,
  lastLoadedAt: null,
  loadAssets: async () => {
    set((state) => ({ status: state.assets.length > 0 ? 'refreshing' : 'loading', error: null }))
    try {
      const assets = await assetService.list()
      set({
        assets,
        status: assets.length === 0 ? 'empty' : 'success',
        error: null,
        lastLoadedAt: Date.now(),
      })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  refreshAssets: async () => {
    await useAssetStore.getState().loadAssets()
  },
  loadProjectAssets: async (projectId) => {
    set((state) => ({
      projectAssets: {
        ...state.projectAssets,
        [projectId]: {
          data: state.projectAssets[projectId]?.data ?? [],
          status: state.projectAssets[projectId]?.data?.length ? 'refreshing' : 'loading',
          error: null,
          lastLoadedAt: state.projectAssets[projectId]?.lastLoadedAt ?? null,
        },
      },
    }))
    try {
      const assets = await assetService.listByProject(projectId)
      set((state) => ({
        projectAssets: {
          ...state.projectAssets,
          [projectId]: {
            data: assets,
            status: assets.length === 0 ? 'empty' : 'success',
            error: null,
            lastLoadedAt: Date.now(),
          },
        },
      }))
    } catch (error) {
      set((state) => ({
        projectAssets: {
          ...state.projectAssets,
          [projectId]: {
            data: state.projectAssets[projectId]?.data ?? [],
            status: 'error',
            error: toApiError(error),
            lastLoadedAt: state.projectAssets[projectId]?.lastLoadedAt ?? null,
          },
        },
      }))
    }
  },
  importAsset: async (request) => {
    set({ status: 'refreshing', error: null })
    try {
      await assetService.importAsset(request)
      await useAssetStore.getState().loadAssets()
      await useAssetStore.getState().loadProjectAssets(request.projectId)
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      throw error
    }
  },
  deleteAsset: async (assetId) => {
    const asset = useAssetStore.getState().assets.find((item) => item.id === assetId)
    await assetService.deleteAsset(assetId)
    await useAssetStore.getState().loadAssets()
    if (asset?.projectId) {
      await useAssetStore.getState().loadProjectAssets(asset.projectId)
    }
  },
  setSelectedAssetId: (selectedAssetId) => set({ selectedAssetId }),
}))
