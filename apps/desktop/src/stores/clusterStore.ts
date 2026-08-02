import { create } from 'zustand'

import type {
  ApiError,
  ApiStatus,
  ClusterHealth,
  ClusterLoad,
  ExecutionLease,
  ExecutionReservation,
  RuntimeExecutionRecord,
  WorkerDetail,
  WorkerNode,
} from '../api/types'
import { clusterService } from '../services/ClusterService'
import { toApiError } from '../services/types'

type ClusterStore = {
  workers: WorkerNode[]
  activeWorker: WorkerDetail | null
  health: ClusterHealth | null
  load: ClusterLoad | null
  reservations: ExecutionReservation[]
  leases: ExecutionLease[]
  waitingPlacement: RuntimeExecutionRecord[]
  lastSweep: string | null
  status: ApiStatus
  error: ApiError | null
  loadCluster: () => Promise<void>
  selectWorker: (workerId: string | null) => Promise<void>
  pauseWorker: (workerId: string) => Promise<void>
  resumeWorker: (workerId: string) => Promise<void>
  drainWorker: (workerId: string) => Promise<void>
  sweep: () => Promise<void>
  recoverExecution: (executionId: string) => Promise<void>
  retryPlacement: (executionId: string) => Promise<void>
}

export const useClusterStore = create<ClusterStore>((set, get) => ({
  workers: [],
  activeWorker: null,
  health: null,
  load: null,
  reservations: [],
  leases: [],
  waitingPlacement: [],
  lastSweep: null,
  status: 'idle',
  error: null,
  loadCluster: async () => {
    set({ status: 'loading', error: null })
    try {
      const [snapshot, reservations, leases, waitingPlacement] = await Promise.all([
        clusterService.snapshot(),
        clusterService.reservations(),
        clusterService.leases(),
        clusterService.waitingPlacement(),
      ])
      const current = get().activeWorker
      set({
        workers: snapshot.workers,
        health: snapshot.health,
        load: snapshot.load,
        reservations,
        leases,
        waitingPlacement,
        status: snapshot.workers.length === 0 ? 'empty' : 'success',
        error: null,
      })
      const stillPresent = snapshot.workers.find((w) => w.id === current?.id)
      await get().selectWorker(stillPresent?.id ?? snapshot.workers[0]?.id ?? null)
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  selectWorker: async (workerId) => {
    if (!workerId) {
      set({ activeWorker: null })
      return
    }
    try {
      const detail = await clusterService.getWorker(workerId)
      set({ activeWorker: detail ?? null })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  pauseWorker: async (workerId) => {
    await applyWorkerAction(set, get, () => clusterService.pause(workerId))
  },
  resumeWorker: async (workerId) => {
    await applyWorkerAction(set, get, () => clusterService.resume(workerId))
  },
  drainWorker: async (workerId) => {
    await applyWorkerAction(set, get, () => clusterService.drain(workerId))
  },
  sweep: async () => {
    set({ status: 'refreshing', error: null })
    try {
      const result = await clusterService.sweep()
      set({
        lastSweep: `${result.workers_marked_offline.length} offline · ${result.leases_expired.length} leases expired · ${result.executions_recovered.length} recovered`,
        status: 'success',
      })
      await get().loadCluster()
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  recoverExecution: async (executionId) => {
    set({ status: 'refreshing', error: null })
    try {
      await clusterService.recover(executionId, 'manual intervention')
      await get().loadCluster()
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  retryPlacement: async (executionId) => {
    set({ status: 'refreshing', error: null })
    try {
      await clusterService.retryPlacement(executionId)
      await get().loadCluster()
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
}))

type SetState = (partial: Partial<ReturnType<typeof useClusterStore.getState>>) => void
type GetState = () => ReturnType<typeof useClusterStore.getState>

async function applyWorkerAction(
  set: SetState,
  get: GetState,
  operation: () => Promise<WorkerNode>,
): Promise<void> {
  set({ status: 'refreshing', error: null })
  try {
    const updated = await operation()
    set({
      workers: get().workers.map((w) => (w.id === updated.id ? updated : w)),
      status: 'success',
      error: null,
    })
    await get().loadCluster()
  } catch (error) {
    set({ status: 'error', error: toApiError(error) })
  }
}
