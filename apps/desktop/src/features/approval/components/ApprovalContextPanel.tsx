import type { ApprovalHistoryEvent, ApprovalRequest } from '../../../api/types'

export function ApprovalContextPanel({
  approval,
  history,
}: {
  approval: ApprovalRequest | null
  history: ApprovalHistoryEvent[]
}) {
  if (!approval) {
    return <p className="text-sm text-slate-500">No approval selected.</p>
  }

  return (
    <div className="space-y-4">
      <section>
        <PanelHeading>Waiting Reason</PanelHeading>
        <p className="rounded bg-slate-900 px-3 py-2 text-sm text-slate-200">
          {approval.reason || 'No reason recorded'}
        </p>
        {approval.policy_name ? (
          <p className="mt-1 text-xs text-slate-500">
            Policy source: <span className="text-slate-300">{approval.policy_name}</span>
          </p>
        ) : null}
      </section>

      <section className="space-y-1.5">
        <PanelHeading>Execution Context</PanelHeading>
        <ContextRow label="Action" value={approval.action || '—'} />
        <ContextRow label="Scopes" value={approval.scopes.join(', ') || 'none'} />
        <ContextRow label="Estimated Cost" value={`$${approval.estimated_cost.toFixed(2)}`} />
        <ContextRow label="Execution" value={approval.execution_id ?? '—'} mono />
        <ContextRow label="Schedule" value={approval.schedule_id ?? '—'} mono />
        <ContextRow label="Agent" value={approval.agent_id ?? '—'} mono />
      </section>

      <section className="space-y-1.5">
        <PanelHeading>Object &amp; Asset</PanelHeading>
        <ContextRow label="Asset" value={approval.asset_id ?? 'No asset attached'} mono />
        <ContextRow label="Run" value={approval.run_id ?? '—'} mono />
        <ContextRow label="Job" value={approval.job_id ?? '—'} mono />
        {Object.keys(approval.payload).length > 0 ? (
          <pre className="max-h-40 overflow-auto rounded bg-slate-900 px-3 py-2 text-xs text-slate-300">
            {JSON.stringify(approval.payload, null, 2)}
          </pre>
        ) : null}
      </section>

      <section className="space-y-1.5">
        <PanelHeading>Approvers</PanelHeading>
        <ContextRow
          label="Required"
          value={approval.required_approvers.join(', ') || 'Any operator'}
        />
        <ContextRow
          label="Quorum"
          value={`${approval.decisions.filter((d) => d.decision === 'approve').length} of ${approval.approvals_required}`}
        />
        <ContextRow label="Requested By" value={approval.requested_by} />
        <ContextRow label="Viewed By" value={approval.viewed_by.join(', ') || 'nobody yet'} />
      </section>

      <section>
        <PanelHeading>Decision History</PanelHeading>
        {history.length === 0 ? (
          <p className="text-sm text-slate-500">No history recorded.</p>
        ) : (
          <ul className="space-y-2">
            {history.map((event) => (
              <li key={event.id} className="rounded bg-slate-900 px-3 py-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs uppercase tracking-widest text-slate-500">
                    {event.event_type}
                  </span>
                  <span className="text-xs text-slate-500">{event.actor}</span>
                </div>
                {event.from_state || event.to_state ? (
                  <p className="mt-1 text-xs text-slate-400">
                    {event.from_state ?? 'none'} → {event.to_state ?? 'none'}
                  </p>
                ) : null}
                {event.comment ? (
                  <p className="mt-1 text-slate-200">{event.comment}</p>
                ) : null}
                <p className="text-xs text-slate-500">
                  {new Date(event.created_at).toLocaleString()}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function PanelHeading({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="mb-1.5 text-xs uppercase tracking-widest text-slate-500">{children}</h4>
  )
}

function ContextRow({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="rounded bg-slate-900 px-3 py-1.5">
      <div className="text-xs uppercase tracking-widest text-slate-500">{label}</div>
      <div className={`mt-0.5 text-sm text-slate-100 ${mono ? 'font-mono text-xs' : ''}`}>
        {value}
      </div>
    </div>
  )
}
