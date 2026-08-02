import { useState } from 'react'

import { Button } from '../../../components'
import type { ApprovalRequest } from '../../../api/types'

type ApprovalDecisionPanelProps = {
  approval: ApprovalRequest | null
  actor: string
  onApprove: (comment?: string) => void
  onReject: (comment?: string) => void
  onRequestChanges: (comment?: string) => void
  onEscalate: (escalatedTo: string) => void
}

export function ApprovalDecisionPanel({
  approval,
  actor,
  onApprove,
  onReject,
  onRequestChanges,
  onEscalate,
}: ApprovalDecisionPanelProps) {
  const [comment, setComment] = useState('')
  const [escalateTo, setEscalateTo] = useState('')

  if (!approval) {
    return <p className="text-sm text-slate-500">Select an approval to review.</p>
  }

  const isSelfRequested = approval.requested_by === actor
  const decided = approval.state !== 'pending'
  const notAnApprover =
    approval.required_approvers.length > 0 && !approval.required_approvers.includes(actor)
  const blocked = decided || isSelfRequested || notAnApprover

  return (
    <div className="space-y-3">
      {blocked ? (
        <p className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {decided
            ? `This request is already ${approval.state} and cannot be changed.`
            : isSelfRequested
              ? `${actor} requested this approval and may not decide it.`
              : `${actor} is not a designated approver for this request.`}
        </p>
      ) : null}

      <textarea
        className="min-h-20 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
        placeholder="Decision comment (optional)"
        value={comment}
        onChange={(event) => setComment(event.target.value)}
        disabled={blocked}
      />

      <div className="grid gap-2 md:grid-cols-3">
        <Button
          variant="accent"
          disabled={blocked}
          onClick={() => {
            onApprove(comment || undefined)
            setComment('')
          }}
        >
          Approve <Shortcut keys="A" />
        </Button>
        <Button
          disabled={blocked}
          onClick={() => {
            onReject(comment || undefined)
            setComment('')
          }}
        >
          Reject <Shortcut keys="R" />
        </Button>
        <Button
          variant="ghost"
          disabled={blocked}
          onClick={() => {
            onRequestChanges(comment || undefined)
            setComment('')
          }}
        >
          Request Changes <Shortcut keys="C" />
        </Button>
      </div>

      <div className="flex gap-2">
        <input
          className="flex-1 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          placeholder="Escalate to approver…"
          value={escalateTo}
          onChange={(event) => setEscalateTo(event.target.value)}
          disabled={decided}
        />
        <Button
          disabled={decided || !escalateTo.trim()}
          onClick={() => {
            onEscalate(escalateTo.trim())
            setEscalateTo('')
          }}
        >
          Escalate
        </Button>
      </div>
    </div>
  )
}

function Shortcut({ keys }: { keys: string }) {
  return (
    <kbd className="ml-1.5 rounded border border-slate-600 bg-slate-800 px-1 text-[10px] text-slate-400">
      {keys}
    </kbd>
  )
}
