import { getAtlasProvider } from '../providers/ProviderContext'

export interface RunService {
  list(): Promise<Awaited<ReturnType<ReturnType<typeof getAtlasProvider>['getRuns']>>>
}

export const runService: RunService = {
  async list() {
    return getAtlasProvider().getRuns()
  },
}
