import { useCallback, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button, Panel } from '../../../components'
import { useApprovalStore, useProjectStore } from '../../../stores'
import type { ApprovalRequest } from '../../../api/types'
import { ApprovalContextPanel } from '../components/ApprovalContextPanel'
import { ApprovalDecisionPanel } from '../components/ApprovalDecisionPanel'

const STATE_STYLES: Record<string, string> = {
  pending: 'text-amber-300',
  approved: 'text-emerald-300',
  rejected: 'text-rose-300',
  cancelled: 'text-slate-400',
  expired: 'text-slate-500',
}

export function ApprovalCenterScreen() {
  const navigate = useNavigate()
  const projects = useProjectStore((state) => state.projects)
  const project = projects[0]

  const approvals = useApprovalStore((state) => state.approvals)
  const activeApproval = useApprovalStore((state) => state.activeApproval)
  const history = useApprovalStore((state) => state.history)
  const policies = useApprovalStore((state) => state.policies)
  const waitingExecutions = useApprovalStore((state) => state.waitingExecutions)
  const actor = useApprovalStore((state) => state.actor)
  const pendingOnly = useApprovalStore((state) => state.pendingOnly)
  const status = useApprovalStore((state) => state.status)
  const error = useApprovalStore((state) => state.error)

  const loadApprovals = useApprovalStore((state) => state.loadApprovals)
  const loadPolicies = useApprovalStore((state) => state.loadPolicies)
  const loadWaitingExecutions = useApprovalStore((state) => state.loadWaitingExecutions)
  const approve = useApprovalStore((state) => state.approve)
  const reject = useApprovalStore((state) => state.reject)
  const requestChanges = useApprovalStore((state) => state.requestChanges)
  const escalate = useApprovalStore((state) => state.escalate)
  const resumeExecution = useApprovalStore((state) => state.resumeExecution)
  const setActiveApproval = useApprovalStore((state) => state.setActiveApproval)
  const setActor = useApprovalStore((state) => state.setActor)
  const setPendingOnly = useApprovalStore((state) => state.setPendingOnly)

  useEffect(() => {
    void loadApprovals(project?.id)
    void loadPolicies(project?.id)
    void loadWaitingExecutions()
  }, [loadApprovals, loadPolicies, loadWaitingExecutions, project?.id, pendingOnly])

  const jumpToAsset = useCallback(() => {
    if (activeApproval?.asset_id) {
      navigate(`/asset/${activeApproval.asset_id}`)
    }
  }, [activeApproval?.asset_id, navigate])

  const jumpToRuntime = useCallback(() => {
    navigate('/activity-center')
  }, [navigate])

  // Keyboard: Approve · Reject · Request Changes · Open Context · Jump to Asset · Jump to Runtime
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null
      const typing =
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      if (typing || event.metaKey || event.ctrlKey || event.altKey || !activeApproval) {
        return
      }

      switch (event.key.toLowerCase()) {
        case 'a':
          event.preventDefault()
          void approve(activeApproval.id)
          break
        case 'r':
          event.preventDefault()
          void reject(activeApproval.id)
          break
        case 'c':
          event.preventDefault()
          void requestChanges(activeApproval.id)
          break
        case 'o':
          event.preventDefault()
          document.getElementById('approval-context')?.scrollIntoView({ behavior: 'smooth' })
          break
        case 'j':
          event.preventDefault()
          jumpToAsset()
          break
        case 'x':
          event.preventDefault()
          jumpToRuntime()
          break
        default:
          break
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [activeApproval, approve, reject, requestChanges, jumpToAsset, jumpToRuntime])

  const pendingCount = useMemo(
    () => approvals.filter((a) => a.state === 'pending').length,
    [approvals],
  )

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[320px_minmax(0,1fr)_360px]">
      <Panel
        title="Pending Approvals"
        subtitle={`${pendingCount} awaiting a decision · ${waitingExecutions.length} execution(s) paused`}
      >
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <input
              className="flex-1 rounded border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-100"
              value={actor}
              onChange={(event) => setActor(event.target.value)}
              placeholder="Acting as…"
            />
            <Button variant="ghost" onClick={() => setPendingOnly(!pendingOnly)}>
              {pendingOnly ? 'All' : 'Pending'}
            </Button>
          </div>

          {error ? (
            <p className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {error.message}
            </p>
          ) : null}

          {approvals.length === 0 ? (
            <p className="rounded border border-dashed border-slate-700 px-3 py-6 text-center text-sm text-slate-500">
              {status === 'loading' ? 'Loading approvals…' : 'Nothing is waiting on you.'}
            </p>
          ) : null}

          <div className="space-y-2">
            {approvals.map((approval) => (
              <ApprovalListItem
                key={approval.id}
                approval={approval}
                selected={activeApproval?.id === approval.id}
                onSelect={() => setActiveApproval(approval)}
              />
            ))}
          </div>
        </div>
      </Panel>

      <div className="space-y-4">
        <Panel
          title={activeApproval?.title ?? 'Decision'}
          subtitle="Nothing executes until a human decides"
        >
          <ApprovalDecisionPanel
            approval={activeApproval}
            actor={actor}
            onApprove={(comment) => activeApproval && void approve(activeApproval.id, comment)}
            onReject={(comment) => activeApproval && void reject(activeApproval.id, comment)}
            onRequestChanges={(comment) =>
              activeApproval && void requestChanges(activeApproval.id, comment)
            }
            onEscalate={(to) => activeApproval && void escalate(activeApproval.id, to)}
          />

          {activeApproval?.state === 'approved' && activeApproval.execution_id ? (
            <div className="mt-3 rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-2">
              <p className="text-sm text-emerald-100">
                Approved. The paused execution can now resume.
              </p>
              <Button
                className="mt-2"
                onClick={() => void resumeExecution(activeApproval.id)}
              >
                Resume Execution
              </Button>
            </div>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="ghost" onClick={jumpToAsset} disabled={!activeApproval?.asset_id}>
              Jump to Asset <Key>J</Key>
            </Button>
            <Button variant="ghost" onClick={jumpToRuntime}>
              Jump to Runtime <Key>X</Key>
            </Button>
          </div>
        </Panel>

        <Panel title="Active Policies" subtitle="Declarative — no rule is hardcoded">
          {policies.length === 0 ? (
            <p className="text-sm text-slate-500">
              No approval policies configured. Without a policy nothing requires approval.
            </p>
          ) : (
            <ul className="space-y-2">
              {policies.map((policy) => (
                <li key={policy.id} className="rounded bg-slate-900 px-3 py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-slate-100">{policy.name}</span>
                    <span className="text-xs uppercase tracking-widest text-slate-500">
                      {policy.mode}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {policy.scopes.join(', ') || 'no scopes'}
                    {policy.cost_threshold != null ? ` · cost > $${policy.cost_threshold}` : ''}
                    {policy.enabled ? '' : ' · disabled'}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div id="approval-context">
        <Panel title="Context" subtitle="Object · asset · graph · execution · approver · age">
          <ApprovalContextPanel approval={activeApproval} history={history} />
        </Panel>
      </div>
    </section>
  )
}

function ApprovalListItem({
  approval,
  selected,
  onSelect,
}: {
  approval: ApprovalRequest
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`block w-full rounded border px-3 py-2 text-left ${
        selected ? 'border-cyan-500/50 bg-cyan-500/10' : 'border-slate-800 bg-slate-900 hover:bg-slate-800'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-slate-100">{approval.title}</span>
        <span
          className={`text-xs uppercase tracking-widest ${STATE_STYLES[approval.state] ?? 'text-slate-400'}`}
        >
          {approval.state}
        </span>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        {approval.scopes.join(', ') || 'no scope'} · priority {approval.priority} ·{' '}
        {formatAge(approval.created_at)}
      </p>
      {approval.required_approvers.length > 0 ? (
        <p className="mt-0.5 text-xs text-slate-500">
          approvers: {approval.required_approvers.join(', ')}
        </p>
      ) : null}
    </button>
  )
}

function Key({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="ml-1.5 rounded border border-slate-600 bg-slate-800 px-1 text-[10px] text-slate-400">
      {children}
    </kbd>
  )
}

function formatAge(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return `${Math.round(seconds)}s old`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m old`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h old`
  return `${Math.round(seconds / 86400)}d old`
}
