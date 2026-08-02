import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  ApprovalCreatePayload,
  ApprovalDecisionPayload,
  ApprovalHistoryEvent,
  ApprovalPolicy,
  ApprovalRequest,
  RuntimeExecutionRecord,
} from '../api/types'

export interface ApprovalService {
  list(params?: { pendingOnly?: boolean; projectId?: string }): Promise<ApprovalRequest[]>
  get(id: string): Promise<ApprovalRequest | undefined>
  create(payload: ApprovalCreatePayload): Promise<ApprovalRequest>
  approve(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest>
  reject(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest>
  requestChanges(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest>
  cancel(id: string, payload: ApprovalDecisionPayload): Promise<ApprovalRequest>
  view(id: string, actor: string): Promise<ApprovalRequest>
  escalate(id: string, actor: string, escalatedTo: string): Promise<ApprovalRequest>
  resumeExecution(id: string): Promise<RuntimeExecutionRecord>
  history(approvalId?: string): Promise<ApprovalHistoryEvent[]>
  policies(projectId?: string): Promise<ApprovalPolicy[]>
  upsertPolicy(policy: Partial<ApprovalPolicy> & { name: string }): Promise<ApprovalPolicy>
  waitingExecutions(): Promise<RuntimeExecutionRecord[]>
}

export const approvalService: ApprovalService = {
  async list(params) {
    return getAtlasProvider().listApprovals(params)
  },
  async get(id) {
    return getAtlasProvider().getApproval(id)
  },
  async create(payload) {
    return getAtlasProvider().createApproval(payload)
  },
  async approve(id, payload) {
    return getAtlasProvider().approveApproval(id, payload)
  },
  async reject(id, payload) {
    return getAtlasProvider().rejectApproval(id, payload)
  },
  async requestChanges(id, payload) {
    return getAtlasProvider().requestChangesApproval(id, payload)
  },
  async cancel(id, payload) {
    return getAtlasProvider().cancelApproval(id, payload)
  },
  async view(id, actor) {
    return getAtlasProvider().viewApproval(id, actor)
  },
  async escalate(id, actor, escalatedTo) {
    return getAtlasProvider().escalateApproval(id, actor, escalatedTo)
  },
  async resumeExecution(id) {
    return getAtlasProvider().resumeApprovedExecution(id)
  },
  async history(approvalId) {
    return getAtlasProvider().getApprovalHistory(approvalId)
  },
  async policies(projectId) {
    return getAtlasProvider().listApprovalPolicies(projectId)
  },
  async upsertPolicy(policy) {
    return getAtlasProvider().upsertApprovalPolicy(policy)
  },
  async waitingExecutions() {
    return getAtlasProvider().listExecutionsWaitingApproval()
  },
}
