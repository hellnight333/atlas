import { getAtlasProvider } from '../providers/ProviderContext'
import type { Capability } from '../api/types'

export interface CapabilityService {
  list(): Promise<Capability[]>
}

export const capabilityService: CapabilityService = {
  async list() {
    return getAtlasProvider().getCapabilities()
  },
}
