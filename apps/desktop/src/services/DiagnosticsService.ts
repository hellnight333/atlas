import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  BackupArchive,
  BackupScope,
  BackupValidation,
  ConfigurationReport,
  DiagnosticsExport,
  HealthReport,
  RecoveryReport,
  RestoreResult,
} from '../api/types'

export interface DiagnosticsService {
  health(): Promise<HealthReport>
  export(): Promise<DiagnosticsExport>
  configuration(): Promise<ConfigurationReport>
  exportBackup(scope: BackupScope, scopeId?: string): Promise<BackupArchive>
  validateBackup(archive: BackupArchive): Promise<BackupValidation>
  restoreBackup(archive: BackupArchive, dryRun?: boolean): Promise<RestoreResult>
  recoveryReport(): Promise<RecoveryReport>
  runSweep(dryRun?: boolean): Promise<RecoveryReport>
}

export const diagnosticsService: DiagnosticsService = {
  async health() {
    return getAtlasProvider().getHealthReport()
  },
  async export() {
    return getAtlasProvider().getDiagnostics()
  },
  async configuration() {
    return getAtlasProvider().getConfiguration()
  },
  async exportBackup(scope, scopeId) {
    return getAtlasProvider().exportBackup(scope, scopeId)
  },
  async validateBackup(archive) {
    return getAtlasProvider().validateBackup(archive)
  },
  async restoreBackup(archive, dryRun) {
    return getAtlasProvider().restoreBackup(archive, dryRun)
  },
  async recoveryReport() {
    return getAtlasProvider().getRecoveryReport()
  },
  async runSweep(dryRun) {
    return getAtlasProvider().runRecoverySweep(dryRun)
  },
}
