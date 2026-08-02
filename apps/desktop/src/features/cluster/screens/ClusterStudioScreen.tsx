import { useEffect } from 'react'

import { Button, Panel } from '../../../components'
import { useClusterStore } from '../../../stores'
import { WorkerCard } from '../components/WorkerCard'
import { WORKER_STATUS_STYLES } from '../constants'

export function ClusterStudioScreen() {
  const workers = useClusterStore((state) => state.workers)
  const activeWorker = useClusterStore((state) => state.activeWorker)
  const health = useClusterStore((state) => state.health)
  const load = useClusterStore((state) => state.load)
  const waitingPlacement = useClusterStore((state) => state.waitingPlacement)
  const lastSweep = useClusterStore((state) => state.lastSweep)
  const status = useClusterStore((state) => state.status)
  const error = useClusterStore((state) => state.error)

  const loadCluster = useClusterStore((state) => state.loadCluster)
  const selectWorker = useClusterStore((state) => state.selectWorker)
  const pauseWorker = useClusterStore((state) => state.pauseWorker)
  const resumeWorker = useClusterStore((state) => state.resumeWorker)
  const drainWorker = useClusterStore((state) => state.drainWorker)
  const sweep = useClusterStore((state) => state.sweep)
  const retryPlacement = useClusterStore((state) => state.retryPlacement)

  useEffect(() => {
    void loadCluster()
  }, [loadCluster])

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[320px_minmax(0,1fr)_360px]">
      <Panel
        title="Workers"
        subtitle={
          health
            ? `${health.online} online · ${health.offline} offline · ${health.draining} draining`
            : 'Loading cluster…'
        }
      >
        <div className="space-y-3">
          {error ? (
            <p className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {error.message}
            </p>
          ) : null}

          {workers.length === 0 ? (
            <p className="rounded border border-dashed border-slate-700 px-3 py-6 text-center text-sm text-slate-500">
              {status === 'loading' ? 'Loading workers…' : 'No workers registered.'}
            </p>
          ) : null}

          <div className="space-y-2">
            {workers.map((worker) => (
              <WorkerCard
                key={worker.id}
                worker={worker}
                selected={activeWorker?.id === worker.id}
                onSelect={() => void selectWorker(worker.id)}
              />
            ))}
          </div>
        </div>
      </Panel>

      <div className="space-y-4">
        <Panel title="Cluster Health" subtitle="Execution location is transparent to the user">
          {health && load ? (
            <div className="grid gap-2 md:grid-cols-3">
              <Stat
                label="Status"
                value={health.healthy ? 'Healthy' : 'Degraded'}
                tone={health.healthy ? 'good' : 'warn'}
              />
              <Stat label="Workers" value={String(health.total_workers)} />
              <Stat
                label="Capacity"
                value={`${load.used_capacity}/${load.total_capacity}`}
                tone={load.load_ratio >= 1 ? 'warn' : 'neutral'}
              />
              <Stat label="Reservations" value={String(load.active_reservations)} />
              <Stat label="Leases" value={String(load.active_leases)} />
              <Stat
                label="Awaiting Placement"
                value={String(waitingPlacement.length)}
                tone={waitingPlacement.length ? 'warn' : 'neutral'}
              />
            </div>
          ) : (
            <p className="text-sm text-slate-500">Loading cluster health…</p>
          )}

          {health && (health.stale_heartbeats.length > 0 || health.expired_leases.length > 0) ? (
            <div className="mt-3 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              {health.stale_heartbeats.length > 0 ? (
                <p>Stale heartbeats: {health.stale_heartbeats.join(', ')}</p>
              ) : null}
              {health.expired_leases.length > 0 ? (
                <p>Expired leases: {health.expired_leases.length}</p>
              ) : null}
            </div>
          ) : null}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button onClick={() => void sweep()}>Run Recovery Sweep</Button>
            <Button variant="ghost" onClick={() => void loadCluster()}>
              Refresh
            </Button>
            {lastSweep ? <span className="text-xs text-slate-500">{lastSweep}</span> : null}
          </div>
        </Panel>

        <Panel title="Execution Placement" subtitle="Which machine is running what">
          {load && load.per_worker.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-widest text-slate-500">
                    <th className="pb-2">Worker</th>
                    <th className="pb-2">Status</th>
                    <th className="pb-2">Load</th>
                    <th className="pb-2">Capabilities</th>
                  </tr>
                </thead>
                <tbody>
                  {load.per_worker.map((summary) => (
                    <tr key={summary.worker_id} className="border-t border-slate-800">
                      <td className="py-2 text-slate-100">{summary.display_name}</td>
                      <td className={`py-2 ${WORKER_STATUS_STYLES[summary.status] ?? 'text-slate-400'}`}>
                        {summary.status}
                      </td>
                      <td className="py-2 text-slate-300">
                        {summary.current_load}/{summary.max_concurrency}
                      </td>
                      <td className="py-2 text-xs text-slate-500">
                        {summary.capabilities.join(', ') || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-slate-500">No placement data.</p>
          )}
        </Panel>

        {waitingPlacement.length > 0 ? (
          <Panel title="Awaiting Placement" subtitle="No worker could take this work yet">
            <ul className="space-y-2">
              {waitingPlacement.map((execution) => (
                <li
                  key={execution.execution_id}
                  className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-amber-100">{execution.action}</span>
                    <Button
                      variant="ghost"
                      onClick={() => void retryPlacement(execution.execution_id)}
                    >
                      Retry Placement
                    </Button>
                  </div>
                  <p className="mt-1 text-xs text-amber-200/70">
                    {execution.placement_reason ?? 'no reason recorded'}
                  </p>
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}
      </div>

      <Panel
        title={activeWorker?.display_name ?? 'Worker Detail'}
        subtitle="Assignments · leases · heartbeats · logs"
      >
        {activeWorker ? (
          <div className="space-y-4">
            <div className="grid gap-2">
              <Button onClick={() => void pauseWorker(activeWorker.id)}>Pause</Button>
              <Button onClick={() => void resumeWorker(activeWorker.id)}>Resume</Button>
              <Button variant="ghost" onClick={() => void drainWorker(activeWorker.id)}>
                Drain
              </Button>
            </div>

            <Section title="Machine">
              <Row label="Hostname" value={activeWorker.hostname} />
              <Row label="Platform" value={activeWorker.platform} />
              <Row label="Version" value={activeWorker.version} />
              <Row
                label="CPU / RAM"
                value={`${activeWorker.resources.cpu_cores} cores · ${activeWorker.resources.ram_gb} GB`}
              />
              <Row
                label="GPU / VRAM"
                value={
                  activeWorker.resources.gpu
                    ? `${activeWorker.resources.gpu} · ${activeWorker.resources.vram_gb} GB`
                    : 'none'
                }
              />
              <Row label="Storage" value={`${activeWorker.resources.storage_gb} GB`} />
            </Section>

            <Section title="Utilisation">
              <Row label="GPU" value={`${activeWorker.metrics.gpu_percent.toFixed(0)}%`} />
              <Row label="Memory" value={`${activeWorker.metrics.ram_percent.toFixed(0)}%`} />
              <Row
                label="Storage Used"
                value={`${activeWorker.metrics.storage_used_gb.toFixed(0)} GB`}
              />
              <Row
                label="Last Heartbeat"
                value={
                  activeWorker.last_heartbeat_at
                    ? new Date(activeWorker.last_heartbeat_at).toLocaleTimeString()
                    : 'never'
                }
              />
            </Section>

            <Section title={`Reservations (${activeWorker.reservations.length})`}>
              {activeWorker.reservations.length === 0 ? (
                <p className="text-xs text-slate-500">No active reservations.</p>
              ) : (
                activeWorker.reservations.map((reservation) => (
                  <p key={reservation.id} className="text-xs text-slate-400">
                    {reservation.capability || 'any'} · {reservation.state}
                  </p>
                ))
              )}
            </Section>

            <Section title={`Leases (${activeWorker.leases.length})`}>
              {activeWorker.leases.length === 0 ? (
                <p className="text-xs text-slate-500">No active leases.</p>
              ) : (
                activeWorker.leases.map((lease) => (
                  <p key={lease.id} className="text-xs text-slate-400">
                    {lease.state} · expires {new Date(lease.expires_at).toLocaleTimeString()}
                  </p>
                ))
              )}
            </Section>

            <Section title="Worker Log">
              {activeWorker.heartbeats.length === 0 ? (
                <p className="text-xs text-slate-500">No heartbeats recorded.</p>
              ) : (
                <ul className="space-y-1">
                  {activeWorker.heartbeats.slice(0, 8).map((hb) => (
                    <li key={hb.id} className="font-mono text-[11px] text-slate-400">
                      {new Date(hb.created_at).toLocaleTimeString()} · {hb.status} · load{' '}
                      {hb.current_load} · gpu {hb.metrics.gpu_percent.toFixed(0)}%
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>
        ) : (
          <p className="text-sm text-slate-500">Select a worker.</p>
        )}
      </Panel>
    </section>
  )
}

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string
  value: string
  tone?: 'neutral' | 'good' | 'warn'
}) {
  const toneClass =
    tone === 'good' ? 'text-emerald-300' : tone === 'warn' ? 'text-amber-300' : 'text-slate-100'
  return (
    <div className="rounded bg-slate-900 px-3 py-2">
      <div className="text-xs uppercase tracking-widest text-slate-500">{label}</div>
      <div className={`mt-1 text-lg font-medium ${toneClass}`}>{value}</div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="mb-1.5 text-xs uppercase tracking-widest text-slate-500">{title}</h4>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2 rounded bg-slate-900 px-3 py-1.5">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-xs text-slate-200">{value}</span>
    </div>
  )
}
