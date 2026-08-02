import { useEffect } from 'react'
import { Link } from 'react-router-dom'

import { ActivityCard, Panel } from '../../../components'
import {
  useActivityStore,
  useApprovalStore,
  useClusterStore,
  useOrganizationStore,
} from '../../../stores'

export function ActivityCenterScreen() {
  const jobs = useActivityStore((state) => state.jobs)
  const approvals = useApprovalStore((state) => state.approvals)
  const waitingExecutions = useApprovalStore((state) => state.waitingExecutions)
  const loadApprovals = useApprovalStore((state) => state.loadApprovals)
  const loadWaitingExecutions = useApprovalStore((state) => state.loadWaitingExecutions)

  const workers = useClusterStore((state) => state.workers)
  const waitingPlacement = useClusterStore((state) => state.waitingPlacement)
  const loadCluster = useClusterStore((state) => state.loadCluster)
  const auditRecords = useOrganizationStore((state) => state.auditRecords)
  const loadOrganizations = useOrganizationStore((state) => state.loadOrganizations)

  useEffect(() => {
    void loadApprovals()
    void loadWaitingExecutions()
    void loadCluster()
    void loadOrganizations()
  }, [loadApprovals, loadWaitingExecutions, loadCluster, loadOrganizations])

  const pending = approvals.filter((approval) => approval.state === 'pending')
  const failedWorkers = workers.filter((w) => w.status === 'offline' || w.status === 'error')
  const governanceEvents = auditRecords.filter((r) =>
    ['permission_changed', 'role_changed', 'policy_changed', 'worker_assignment'].includes(r.action),
  )

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[1.2fr_1fr]">
      <Panel title="Activity Timeline" subtitle="Running, blocked, warning, and failure records">
        <div className="space-y-2">
          {pending.map((approval) => (
            <Link
              key={approval.id}
              to="/approvals"
              className="block rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 hover:border-amber-400"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-amber-100">{approval.title}</span>
                <span className="text-xs uppercase tracking-widest text-amber-300">
                  waiting approval
                </span>
              </div>
              <p className="mt-1 text-xs text-amber-200/70">
                {approval.reason || 'Awaiting a human decision'}
              </p>
            </Link>
          ))}
          {failedWorkers.map((worker) => (
            <Link
              key={worker.id}
              to="/cluster"
              className="block rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 hover:border-rose-400"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-rose-100">{worker.display_name}</span>
                <span className="text-xs uppercase tracking-widest text-rose-300">
                  worker {worker.status}
                </span>
              </div>
              <p className="mt-1 text-xs text-rose-200/70">
                Work assigned here will be recovered onto another machine.
              </p>
            </Link>
          ))}
          {waitingPlacement.map((execution) => (
            <Link
              key={execution.execution_id}
              to="/cluster"
              className="block rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 hover:border-amber-400"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-amber-100">{execution.action}</span>
                <span className="text-xs uppercase tracking-widest text-amber-300">
                  awaiting placement
                </span>
              </div>
              <p className="mt-1 text-xs text-amber-200/70">
                {execution.placement_reason ?? 'No worker available'}
              </p>
            </Link>
          ))}
          {governanceEvents.slice(0, 6).map((record) => (
            <Link
              key={record.id}
              to="/organizations"
              className="block rounded border border-indigo-500/40 bg-indigo-500/10 px-3 py-2 hover:border-indigo-400"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-indigo-100">{record.summary}</span>
                <span className="text-xs uppercase tracking-widest text-indigo-300">
                  {record.action.replace('_', ' ')}
                </span>
              </div>
              <p className="mt-1 text-xs text-indigo-200/70">by {record.actor_display}</p>
            </Link>
          ))}
          {jobs.map((job) => (
            <ActivityCard key={job.id} job={job} />
          ))}
        </div>
      </Panel>
      <div className="space-y-4">
        <Panel
          title="Waiting on You"
          subtitle={`${pending.length} approval(s) · ${waitingExecutions.length} paused execution(s)`}
        >
          {pending.length === 0 ? (
            <p className="text-sm text-slate-500">Nothing is waiting for a decision.</p>
          ) : (
            <Link
              to="/approvals"
              className="inline-block rounded border border-cyan-500/50 bg-cyan-500/15 px-3 py-1.5 text-sm text-cyan-200 hover:border-cyan-400"
            >
              Open Approval Center
            </Link>
          )}
        </Panel>
        <Panel title="Domain Groups" subtitle="Rendering, research, training, publishing, downloads, uploads">
          <ul className="space-y-1 text-sm text-slate-300">
            <li>Rendering</li>
            <li>Research</li>
            <li>Training</li>
            <li>Publishing</li>
            <li>Downloads</li>
            <li>Uploads</li>
          </ul>
        </Panel>
      </div>
    </section>
  )
}
