import type { AgentTask, Job, NotificationItem } from '../types/domain'
import { getAtlasProvider } from '../providers/ProviderContext'

export interface ActivityService {
  listJobs(): Promise<Job[]>
  listAgentTasks(): Promise<AgentTask[]>
  listNotifications(): Promise<NotificationItem[]>
}

export const activityService: ActivityService = {
  async listJobs() {
    return getAtlasProvider().getActivities()
  },
  async listAgentTasks() {
    return getAtlasProvider().getAgentTasks()
  },
  async listNotifications() {
    return getAtlasProvider().getNotifications()
  },
}
