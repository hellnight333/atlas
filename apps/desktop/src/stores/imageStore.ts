import { create } from 'zustand'

import type { ApiError, ApiStatus, ImageAsset, ImageGenerateRequest, ImageVariantRequest } from '../api/types'
import { imageService } from '../services/ImageService'
import { toApiError } from '../services/types'

type ImageStore = {
  images: ImageAsset[]
  versions: Record<string, ImageAsset[]>
  selectedImageId: string | null
  status: ApiStatus
  error: ApiError | null
  lastLoadedAt: number | null
  loadImages: (projectId?: string) => Promise<void>
  refreshImages: (projectId?: string) => Promise<void>
  loadImageVersions: (id: string) => Promise<void>
  generateImage: (request: ImageGenerateRequest) => Promise<ImageAsset | null>
  createVariant: (id: string, request: ImageVariantRequest) => Promise<ImageAsset | null>
  regenerateImage: (id: string, request: ImageVariantRequest) => Promise<ImageAsset | null>
  setSelectedImageId: (id: string | null) => void
}

export const useImageStore = create<ImageStore>((set, get) => ({
  images: [],
  versions: {},
  selectedImageId: null,
  status: 'idle',
  error: null,
  lastLoadedAt: null,
  loadImages: async (projectId) => {
    set((state) => ({ status: state.images.length > 0 ? 'refreshing' : 'loading', error: null }))
    try {
      const images = await imageService.list(projectId)
      set((state) => ({
        images,
        status: images.length === 0 ? 'empty' : 'success',
        error: null,
        lastLoadedAt: Date.now(),
        selectedImageId:
          state.selectedImageId && images.some((image) => image.id === state.selectedImageId)
            ? state.selectedImageId
            : images[0]?.id ?? null,
      }))
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  refreshImages: async (projectId) => {
    await get().loadImages(projectId)
  },
  loadImageVersions: async (id) => {
    try {
      const versions = await imageService.versions(id)
      set((state) => ({ versions: { ...state.versions, [id]: versions } }))
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  generateImage: async (request) => {
    set({ status: 'refreshing', error: null })
    try {
      const result = await imageService.generate(request)
      const created = result.image
      set((state) => ({
        images: [created, ...state.images.filter((item) => item.id !== created.id)],
        selectedImageId: created.id,
        status: 'success',
        error: null,
        lastLoadedAt: Date.now(),
      }))
      await get().loadImageVersions(created.id)
      return created
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  createVariant: async (id, request) => {
    set({ status: 'refreshing', error: null })
    try {
      const result = await imageService.variant(id, request)
      const created = result.image
      set((state) => ({
        images: [created, ...state.images.filter((item) => item.id !== created.id)],
        selectedImageId: created.id,
        status: 'success',
        error: null,
        lastLoadedAt: Date.now(),
      }))
      await get().loadImageVersions(id)
      return created
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  regenerateImage: async (id, request) => {
    set({ status: 'refreshing', error: null })
    try {
      const result = await imageService.regenerate(id, request)
      const created = result.image
      set((state) => ({
        images: [created, ...state.images.filter((item) => item.id !== created.id)],
        selectedImageId: created.id,
        status: 'success',
        error: null,
        lastLoadedAt: Date.now(),
      }))
      await get().loadImageVersions(id)
      return created
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  setSelectedImageId: (selectedImageId) => set({ selectedImageId }),
}))
