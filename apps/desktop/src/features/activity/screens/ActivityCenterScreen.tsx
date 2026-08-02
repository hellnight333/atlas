import { useEffect } from 'react'
import { Link } from 'react-router-dom'

import { ActivityCard, Panel } from '../../../components'
import { useActivityStore, useApprovalStore } from '../../../stores'

export function ActivityCenterScreen() {
  const jobs = useActivityStore((state) => state.jobs)
  const approvals = useApprovalStore((state) => state.approvals)
  const waitingExecutions = useApprovalStore((state) => state.waitingExecutions)
  const loadApprovals = useApprovalStore((state) => state.loadApprovals)
  const loadWaitingExecutions = useApprovalStore((state) => state.loadWaitingExecutions)

  useEffect(() => {
    void loadApprovals()
    void loadWaitingExecutions()
  }, [loadApprovals, loadWaitingExecutions])

  const pending = approvals.filter((approval) => approval.state === 'pending')

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
