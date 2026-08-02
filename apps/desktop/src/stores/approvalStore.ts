import { create } from 'zustand'

import type {
  ApiError,
  ApiStatus,
  ApprovalHistoryEvent,
  ApprovalPolicy,
  ApprovalRequest,
  RuntimeExecutionRecord,
} from '../api/types'
import { approvalService } from '../services/ApprovalService'
import { toApiError } from '../services/types'

type ApprovalStore = {
  approvals: ApprovalRequest[]
  activeApproval: ApprovalRequest | null
  history: ApprovalHistoryEvent[]
  policies: ApprovalPolicy[]
  waitingExecutions: RuntimeExecutionRecord[]
  actor: string
  pendingOnly: boolean
  status: ApiStatus
  error: ApiError | null
  loadApprovals: (projectId?: string) => Promise<void>
  loadHistory: (approvalId: string) => Promise<void>
  loadPolicies: (projectId?: string) => Promise<void>
  loadWaitingExecutions: () => Promise<void>
  approve: (id: string, comment?: string) => Promise<void>
  reject: (id: string, comment?: string) => Promise<void>
  requestChanges: (id: string, comment?: string) => Promise<void>
  cancel: (id: string, comment?: string) => Promise<void>
  escalate: (id: string, escalatedTo: string) => Promise<void>
  resumeExecution: (id: string) => Promise<void>
  setActiveApproval: (approval: ApprovalRequest | null) => void
  setActor: (actor: string) => void
  setPendingOnly: (pendingOnly: boolean) => void
}

export const useApprovalStore = create<ApprovalStore>((set, get) => ({
  approvals: [],
  activeApproval: null,
  history: [],
  policies: [],
  waitingExecutions: [],
  actor: 'operator',
  pendingOnly: true,
  status: 'idle',
  error: null,
  loadApprovals: async (projectId) => {
    set({ status: 'loading', error: null })
    try {
      const approvals = await approvalService.list({
        pendingOnly: get().pendingOnly,
        projectId,
      })
      const current = get().activeApproval
      const next = approvals.find((a) => a.id === current?.id) ?? approvals[0] ?? null
      set({
        approvals,
        activeApproval: next,
        status: approvals.length === 0 ? 'empty' : 'success',
        error: null,
      })
      if (next) {
        await get().loadHistory(next.id)
      } else {
        set({ history: [] })
      }
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  loadHistory: async (approvalId) => {
    try {
      const history = await approvalService.history(approvalId)
      set({ history })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  loadPolicies: async (projectId) => {
    try {
      const policies = await approvalService.policies(projectId)
      set({ policies })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  loadWaitingExecutions: async () => {
    try {
      const waitingExecutions = await approvalService.waitingExecutions()
      set({ waitingExecutions })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  approve: async (id, comment) => {
    await applyDecision(set, get, () =>
      approvalService.approve(id, { actor: get().actor, comment }),
    )
  },
  reject: async (id, comment) => {
    await applyDecision(set, get, () =>
      approvalService.reject(id, { actor: get().actor, comment }),
    )
  },
  requestChanges: async (id, comment) => {
    await applyDecision(set, get, () =>
      approvalService.requestChanges(id, { actor: get().actor, comment }),
    )
  },
  cancel: async (id, comment) => {
    await applyDecision(set, get, () =>
      approvalService.cancel(id, { actor: get().actor, comment }),
    )
  },
  escalate: async (id, escalatedTo) => {
    await applyDecision(set, get, () =>
      approvalService.escalate(id, get().actor, escalatedTo),
    )
  },
  resumeExecution: async (id) => {
    set({ status: 'refreshing', error: null })
    try {
      await approvalService.resumeExecution(id)
      set({ status: 'success', error: null })
      await get().loadWaitingExecutions()
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  setActiveApproval: (approval) => {
    set({ activeApproval: approval })
    if (approval) {
      void get().loadHistory(approval.id)
      void approvalService.view(approval.id, get().actor).catch(() => undefined)
    } else {
      set({ history: [] })
    }
  },
  setActor: (actor) => set({ actor }),
  setPendingOnly: (pendingOnly) => set({ pendingOnly }),
}))

type SetState = (partial: Partial<ReturnType<typeof useApprovalStore.getState>>) => void
type GetState = () => ReturnType<typeof useApprovalStore.getState>

async function applyDecision(
  set: SetState,
  get: GetState,
  operation: () => Promise<ApprovalRequest>,
): Promise<void> {
  set({ status: 'refreshing', error: null })
  try {
    const updated = await operation()
    set({
      approvals: get().approvals.map((a) => (a.id === updated.id ? updated : a)),
      activeApproval: updated,
      status: 'success',
      error: null,
    })
    await get().loadHistory(updated.id)
    if (get().pendingOnly && updated.state !== 'pending') {
      await get().loadApprovals()
    }
  } catch (error) {
    set({ status: 'error', error: toApiError(error) })
  }
}
