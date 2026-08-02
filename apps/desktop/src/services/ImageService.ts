import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  ImageAsset,
  ImageGenerateRequest,
  ImageGenerationResult,
  ImageVariantRequest,
} from '../api/types'

export interface ImageService {
  generate(request: ImageGenerateRequest): Promise<ImageGenerationResult>
  list(projectId?: string): Promise<ImageAsset[]>
  getById(id: string): Promise<ImageAsset | undefined>
  variant(id: string, request: ImageVariantRequest): Promise<ImageGenerationResult>
  regenerate(id: string, request: ImageVariantRequest): Promise<ImageGenerationResult>
  versions(id: string): Promise<ImageAsset[]>
}

export const imageService: ImageService = {
  async generate(request) {
    return getAtlasProvider().generateImage(request)
  },
  async list(projectId) {
    return getAtlasProvider().listImages(projectId)
  },
  async getById(id) {
    return getAtlasProvider().getImage(id)
  },
  async variant(id, request) {
    return getAtlasProvider().createImageVariant(id, request)
  },
  async regenerate(id, request) {
    return getAtlasProvider().regenerateImage(id, request)
  },
  async versions(id) {
    return getAtlasProvider().getImageVersions(id)
  },
}
