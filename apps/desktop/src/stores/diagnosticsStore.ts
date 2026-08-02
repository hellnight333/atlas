import { create } from 'zustand'

import type {
  ApiError,
  ApiStatus,
  BackupArchive,
  BackupScope,
  BackupValidation,
  ConfigurationReport,
  DiagnosticsExport,
  HealthReport,
  RecoveryReport,
  RestoreResult,
} from '../api/types'
import { diagnosticsService } from '../services/DiagnosticsService'
import { toApiError } from '../services/types'

type DiagnosticsStore = {
  health: HealthReport | null
  diagnostics: DiagnosticsExport | null
  configuration: ConfigurationReport | null
  recovery: RecoveryReport | null
  archive: BackupArchive | null
  validation: BackupValidation | null
  restoreResult: RestoreResult | null
  status: ApiStatus
  error: ApiError | null
  load: () => Promise<void>
  refreshRecovery: () => Promise<void>
  runSweep: (dryRun: boolean) => Promise<void>
  exportBackup: (scope: BackupScope, scopeId?: string) => Promise<void>
  validateArchive: () => Promise<void>
  restoreArchive: (dryRun: boolean) => Promise<void>
  clearArchive: () => void
}

export const useDiagnosticsStore = create<DiagnosticsStore>((set, get) => ({
  health: null,
  diagnostics: null,
  configuration: null,
  recovery: null,
  archive: null,
  validation: null,
  restoreResult: null,
  status: 'idle',
  error: null,
  load: async () => {
    set({ status: 'loading', error: null })
    try {
      const [health, diagnostics, configuration, recovery] = await Promise.all([
        diagnosticsService.health(),
        diagnosticsService.export(),
        diagnosticsService.configuration(),
        diagnosticsService.recoveryReport(),
      ])
      set({ health, diagnostics, configuration, recovery, status: 'success', error: null })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  refreshRecovery: async () => {
    try {
      set({ recovery: await diagnosticsService.recoveryReport() })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  runSweep: async (dryRun) => {
    set({ status: 'refreshing', error: null })
    try {
      const recovery = await diagnosticsService.runSweep(dryRun)
      set({ recovery, status: 'success' })
      if (!dryRun) {
        await get().load()
      }
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  exportBackup: async (scope, scopeId) => {
    set({ status: 'refreshing', error: null, validation: null, restoreResult: null })
    try {
      const archive = await diagnosticsService.exportBackup(scope, scopeId)
      set({ archive, status: 'success' })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  validateArchive: async () => {
    const archive = get().archive
    if (!archive) return
    try {
      set({ validation: await diagnosticsService.validateBackup(archive) })
    } catch (error) {
      set({ error: toApiError(error) })
    }
  },
  restoreArchive: async (dryRun) => {
    const archive = get().archive
    if (!archive) return
    set({ status: 'refreshing', error: null })
    try {
      const restoreResult = await diagnosticsService.restoreBackup(archive, dryRun)
      set({ restoreResult, status: 'success' })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  clearArchive: () => set({ archive: null, validation: null, restoreResult: null }),
}))
