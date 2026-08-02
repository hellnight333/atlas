import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  ClusterHealth,
  ClusterLoad,
  ClusterSnapshot,
  ClusterSweepResult,
  ExecutionLease,
  ExecutionReservation,
  RuntimeExecutionRecord,
  WorkerDetail,
  WorkerHeartbeatPayload,
  WorkerNode,
  WorkerRegisterPayload,
  WorkerStatus,
} from '../api/types'

export interface ClusterService {
  listWorkers(status?: WorkerStatus): Promise<WorkerNode[]>
  getWorker(id: string): Promise<WorkerDetail | undefined>
  register(payload: WorkerRegisterPayload): Promise<WorkerNode>
  heartbeat(payload: WorkerHeartbeatPayload): Promise<WorkerNode>
  pause(id: string): Promise<WorkerNode>
  resume(id: string): Promise<WorkerNode>
  drain(id: string): Promise<WorkerNode>
  snapshot(): Promise<ClusterSnapshot>
  health(): Promise<ClusterHealth>
  load(): Promise<ClusterLoad>
  reservations(workerId?: string): Promise<ExecutionReservation[]>
  leases(workerId?: string): Promise<ExecutionLease[]>
  waitingPlacement(): Promise<RuntimeExecutionRecord[]>
  sweep(): Promise<ClusterSweepResult>
  recover(executionId: string, reason?: string): Promise<RuntimeExecutionRecord>
  retryPlacement(executionId: string): Promise<RuntimeExecutionRecord>
}

export const clusterService: ClusterService = {
  async listWorkers(status) {
    return getAtlasProvider().listWorkers(status)
  },
  async getWorker(id) {
    return getAtlasProvider().getWorker(id)
  },
  async register(payload) {
    return getAtlasProvider().registerWorker(payload)
  },
  async heartbeat(payload) {
    return getAtlasProvider().sendWorkerHeartbeat(payload)
  },
  async pause(id) {
    return getAtlasProvider().pauseWorker(id)
  },
  async resume(id) {
    return getAtlasProvider().resumeWorker(id)
  },
  async drain(id) {
    return getAtlasProvider().drainWorker(id)
  },
  async snapshot() {
    return getAtlasProvider().getCluster()
  },
  async health() {
    return getAtlasProvider().getClusterHealth()
  },
  async load() {
    return getAtlasProvider().getClusterLoad()
  },
  async reservations(workerId) {
    return getAtlasProvider().listReservations(workerId)
  },
  async leases(workerId) {
    return getAtlasProvider().listLeases(workerId)
  },
  async waitingPlacement() {
    return getAtlasProvider().listExecutionsWaitingPlacement()
  },
  async sweep() {
    return getAtlasProvider().sweepCluster()
  },
  async recover(executionId, reason) {
    return getAtlasProvider().recoverExecution(executionId, reason)
  },
  async retryPlacement(executionId) {
    return getAtlasProvider().retryPlacement(executionId)
  },
}
