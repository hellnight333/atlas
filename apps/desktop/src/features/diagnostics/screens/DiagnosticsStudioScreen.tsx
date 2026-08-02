import { useEffect, useState } from 'react'

import { Button, Panel } from '../../../components'
import { useDiagnosticsStore, useProjectStore } from '../../../stores'
import type { BackupScope, ComponentStatus } from '../../../api/types'

const BACKUP_SCOPES: BackupScope[] = ['project', 'workspace', 'organization', 'settings']

export function DiagnosticsStudioScreen() {
  const projects = useProjectStore((state) => state.projects)

  const health = useDiagnosticsStore((state) => state.health)
  const diagnostics = useDiagnosticsStore((state) => state.diagnostics)
  const configuration = useDiagnosticsStore((state) => state.configuration)
  const recovery = useDiagnosticsStore((state) => state.recovery)
  const archive = useDiagnosticsStore((state) => state.archive)
  const validation = useDiagnosticsStore((state) => state.validation)
  const restoreResult = useDiagnosticsStore((state) => state.restoreResult)
  const status = useDiagnosticsStore((state) => state.status)
  const error = useDiagnosticsStore((state) => state.error)

  const load = useDiagnosticsStore((state) => state.load)
  const runSweep = useDiagnosticsStore((state) => state.runSweep)
  const exportBackup = useDiagnosticsStore((state) => state.exportBackup)
  const validateArchive = useDiagnosticsStore((state) => state.validateArchive)
  const restoreArchive = useDiagnosticsStore((state) => state.restoreArchive)
  const clearArchive = useDiagnosticsStore((state) => state.clearArchive)

  const [scope, setScope] = useState<BackupScope>('project')
  const [scopeId, setScopeId] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    void load()
  }, [load])

  const loading = status === 'loading'

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-4">
        <Panel
          title="System Health"
          subtitle={
            health
              ? health.healthy
                ? 'All components reporting healthy'
                : `Degraded: ${health.components.filter((c) => !c.healthy).length} component(s)`
              : 'Loading…'
          }
        >
          {error ? (
            <p
              role="alert"
              className="mb-3 rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"
            >
              {error.message}
            </p>
          ) : null}

          {loading ? (
            <LoadingRows rows={6} />
          ) : !health ? (
            <EmptyState message="No health data available." />
          ) : (
            <ul className="space-y-2">
              {health.components.map((component) => (
                <ComponentRow key={component.name} component={component} />
              ))}
            </ul>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={() => void load()}>Refresh</Button>
            {diagnostics ? (
              <Button
                variant="ghost"
                onClick={() => {
                  void navigator.clipboard
                    ?.writeText(JSON.stringify(diagnostics, null, 2))
                    .then(() => setCopied(true))
                    .catch(() => setCopied(false))
                }}
              >
                {copied ? 'Copied ✓' : 'Copy Diagnostics'}
              </Button>
            ) : null}
          </div>
        </Panel>

        <Panel title="Recovery" subtitle="Repairs work stranded by a crash or a dead worker">
          {!recovery ? (
            <LoadingRows rows={2} />
          ) : recovery.actions.length === 0 ? (
            <EmptyState message="Nothing needs recovery." />
          ) : (
            <ul className="space-y-2">
              {recovery.actions.slice(0, 10).map((action) => (
                <li
                  key={`${action.kind}-${action.target_id}`}
                  className="rounded bg-slate-900 px-3 py-2 text-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-slate-100">{action.kind.replace(/_/g, ' ')}</span>
                    <span className="font-mono text-[11px] text-slate-500">
                      {action.target_id}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{action.detail}</p>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={() => void runSweep(true)}>Preview Sweep</Button>
            <Button variant="accent" onClick={() => void runSweep(false)}>
              Run Recovery
            </Button>
          </div>
        </Panel>

        <Panel title="Backup &amp; Restore" subtitle="Metadata archives — asset bytes stay in the store">
          <div className="space-y-3">
            <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
              <label className="sr-only" htmlFor="backup-scope">
                Backup scope
              </label>
              <select
                id="backup-scope"
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                value={scope}
                onChange={(event) => setScope(event.target.value as BackupScope)}
              >
                {BACKUP_SCOPES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
              <label className="sr-only" htmlFor="backup-scope-id">
                Scope identifier
              </label>
              <select
                id="backup-scope-id"
                className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
                value={scopeId}
                onChange={(event) => setScopeId(event.target.value)}
                disabled={scope === 'settings'}
              >
                <option value="">Select target…</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
              <Button
                disabled={scope !== 'settings' && !scopeId}
                onClick={() => void exportBackup(scope, scopeId || undefined)}
              >
                Export
              </Button>
            </div>

            {archive ? (
              <div className="rounded border border-slate-700 bg-slate-950 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm text-slate-100">
                    {archive.manifest.scope} backup
                  </span>
                  <span className="font-mono text-[11px] text-slate-500">
                    {archive.manifest.checksum.slice(0, 12)}…
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {Object.entries(archive.manifest.counts)
                    .map(([section, count]) => `${section}: ${count}`)
                    .join(' · ') || 'empty'}
                </p>

                <div className="mt-2 flex flex-wrap gap-2">
                  <Button onClick={() => void validateArchive()}>Validate</Button>
                  <Button onClick={() => void restoreArchive(true)}>Dry-Run Restore</Button>
                  <Button variant="accent" onClick={() => void restoreArchive(false)}>
                    Restore
                  </Button>
                  <Button variant="ghost" onClick={clearArchive}>
                    Discard
                  </Button>
                </div>

                {validation ? (
                  <p
                    className={`mt-2 rounded px-3 py-2 text-xs ${
                      validation.valid
                        ? 'bg-emerald-500/10 text-emerald-200'
                        : 'bg-rose-500/10 text-rose-200'
                    }`}
                  >
                    {validation.valid
                      ? 'Archive is valid'
                      : validation.errors.join('; ') || 'Archive is invalid'}
                  </p>
                ) : null}

                {restoreResult ? (
                  <p className="mt-2 rounded bg-slate-900 px-3 py-2 text-xs text-slate-300">
                    {restoreResult.dry_run ? 'Dry run — ' : ''}
                    restored{' '}
                    {Object.values(restoreResult.restored).reduce((a, b) => a + b, 0)} record(s),
                    skipped{' '}
                    {Object.values(restoreResult.skipped).reduce((a, b) => a + b, 0)}
                  </p>
                ) : null}
              </div>
            ) : (
              <EmptyState message="No archive loaded. Export one to validate or restore." />
            )}
          </div>
        </Panel>
      </div>

      <div className="space-y-4">
        <Panel title="Environment" subtitle="Never includes credentials">
          {!diagnostics ? (
            <LoadingRows rows={4} />
          ) : (
            <dl className="space-y-1.5">
              {Object.entries(diagnostics.environment).map(([key, value]) => (
                <Row key={key} label={key.replace(/_/g, ' ')} value={String(value)} />
              ))}
            </dl>
          )}
        </Panel>

        <Panel title="System" subtitle="Host and interpreter">
          {!diagnostics ? (
            <LoadingRows rows={3} />
          ) : (
            <dl className="space-y-1.5">
              {Object.entries(diagnostics.system).map(([key, value]) => (
                <Row key={key} label={key.replace(/_/g, ' ')} value={String(value)} />
              ))}
            </dl>
          )}
        </Panel>

        <Panel title="Dependencies" subtitle="Required packages">
          {!diagnostics ? (
            <LoadingRows rows={3} />
          ) : (
            <ul className="space-y-1">
              {diagnostics.dependencies.map((dependency) => (
                <li
                  key={dependency.name}
                  className="flex items-center justify-between rounded bg-slate-900 px-3 py-1.5 text-xs"
                >
                  <span className="text-slate-200">{dependency.name}</span>
                  <span
                    className={dependency.installed ? 'text-emerald-300' : 'text-rose-300'}
                  >
                    {dependency.installed ? (dependency.version ?? 'installed') : 'missing'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Configuration Profiles" subtitle="Declarative — environment always wins">
          {!configuration ? (
            <LoadingRows rows={3} />
          ) : (
            <ul className="space-y-1.5">
              {configuration.profiles.map((profile) => (
                <li key={profile.profile} className="rounded bg-slate-900 px-3 py-2 text-xs">
                  <div className="text-slate-100">{profile.profile}</div>
                  <div className="mt-0.5 font-mono text-[11px] text-slate-500">
                    {Object.entries(profile.defaults)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(' ')}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </section>
  )
}

function ComponentRow({ component }: { component: ComponentStatus }) {
  return (
    <li className="rounded bg-slate-900 px-3 py-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="text-slate-100">{component.name}</span>
        <span
          className={`text-xs uppercase tracking-widest ${
            component.healthy ? 'text-emerald-300' : 'text-rose-300'
          }`}
        >
          {component.healthy ? 'healthy' : 'degraded'}
        </span>
      </div>
      <p className="mt-1 text-xs text-slate-500">{component.detail}</p>
    </li>
  )
}

function LoadingRows({ rows }: { rows: number }) {
  return (
    <div aria-busy="true" aria-live="polite" className="space-y-2">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="h-9 animate-pulse rounded bg-slate-900" />
      ))}
    </div>
  )
}

function EmptyState({ message }: { message: string }) {
  return (
    <p className="rounded border border-dashed border-slate-700 px-3 py-6 text-center text-sm text-slate-500">
      {message}
    </p>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2 rounded bg-slate-900 px-3 py-1.5">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-xs text-slate-200">{value}</dd>
    </div>
  )
}
