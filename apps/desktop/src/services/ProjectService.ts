import { getAtlasProvider } from '../providers/ProviderContext'
import type { Project } from '../types/domain'

export interface ProjectService {
  list(): Promise<Project[]>
  getById(id: string): Promise<Project | undefined>
}

export const projectService: ProjectService = {
  async list() {
    return getAtlasProvider().getProjects()
  },
  async getById(id) {
    return getAtlasProvider().getProject(id)
  },
}
