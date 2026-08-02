import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  ResearchGraph,
  ResearchReportRequest,
  ResearchSearchRequest,
  ResearchSession,
  ResearchSessionRequest,
  ResearchSummarizeRequest,
} from '../api/types'

export interface ResearchService {
  createSession(request: ResearchSessionRequest): Promise<ResearchSession>
  listSessions(projectId?: string): Promise<ResearchSession[]>
  getSession(id: string): Promise<ResearchSession | undefined>
  search(request: ResearchSearchRequest): Promise<{ session_id: string; provider: string; sources: Array<Record<string, unknown>> }>
  summarize(request: ResearchSummarizeRequest): Promise<{ run_id: string; job_id: string; provider: string; asset: Record<string, unknown> }>
  report(request: ResearchReportRequest): Promise<Record<string, unknown>>
  getGraph(projectId: string): Promise<ResearchGraph>
}

export const researchService: ResearchService = {
  async createSession(request) {
    return getAtlasProvider().createResearchSession(request)
  },
  async listSessions(projectId) {
    return getAtlasProvider().listResearchSessions(projectId)
  },
  async getSession(id) {
    return getAtlasProvider().getResearchSession(id)
  },
  async search(request) {
    return getAtlasProvider().searchResearch(request)
  },
  async summarize(request) {
    return getAtlasProvider().summarizeResearch(request)
  },
  async report(request) {
    return getAtlasProvider().generateResearchReport(request)
  },
  async getGraph(projectId) {
    return getAtlasProvider().getResearchGraph(projectId)
  },
}