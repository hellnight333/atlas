import { useEffect, useMemo, useState } from 'react'

import { Button, Panel } from '../../../components'
import { useActivityStore, useAssetStore, useProjectStore, useReviewStore } from '../../../stores'

export function ReviewStudioScreen() {
  const projects = useProjectStore((state) => state.projects)
  const project = projects[0]
  const assets = useAssetStore((state) => state.assets)
  const activity = useActivityStore((state) => state.jobs)

  const sessions = useReviewStore((state) => state.sessions)
  const activeSession = useReviewStore((state) => state.activeSession)
  const history = useReviewStore((state) => state.history)
  const loadSessions = useReviewStore((state) => state.loadSessions)
  const createSession = useReviewStore((state) => state.createSession)
  const approve = useReviewStore((state) => state.approve)
  const reject = useReviewStore((state) => state.reject)
  const publish = useReviewStore((state) => state.publish)
  const comment = useReviewStore((state) => state.comment)
  const setActiveSession = useReviewStore((state) => state.setActiveSession)

  const [title, setTitle] = useState('Review Session 001')
  const [commentDraft, setCommentDraft] = useState('')

  useEffect(() => {
    if (project) {
      void loadSessions(project.id)
    }
  }, [loadSessions, project])

  const selectedAssetId = useMemo(() => activeSession?.asset_id ?? assets[0]?.id, [activeSession?.asset_id, assets])

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[280px_minmax(0,1fr)_320px]">
      <Panel title="Review Queue" subtitle="Pending reviews, stages, assignment placeholders">
        <div className="space-y-3">
          <input
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Review title"
          />
          <Button
            onClick={() => {
              if (!project) {
                return
              }
              void createSession(project.id, title, assets[0]?.id)
            }}
          >
            Create Review
          </Button>
          <div className="space-y-2">
            {sessions.map((session) => (
              <button
                key={session.id}
                type="button"
                className={`block w-full rounded px-3 py-2 text-left text-sm ${activeSession?.id === session.id ? 'bg-emerald-500/15 text-emerald-100' : 'bg-slate-900 text-slate-300 hover:bg-slate-800'}`}
                onClick={() => setActiveSession(session)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{session.title}</span>
                  <span className="text-xs uppercase tracking-widest text-slate-500">{session.status}</span>
                </div>
                <p className="mt-1 text-xs text-slate-500">{session.asset_id ?? 'No asset selected'}</p>
              </button>
            ))}
          </div>
        </div>
      </Panel>

      <Panel title="Review Workspace" subtitle="Diffs, comments, approval controls, publish actions">
        <div className="space-y-4">
          <div className="grid gap-3 rounded border border-slate-700 bg-slate-950 p-3 md:grid-cols-2">
            <Button
              variant="accent"
              onClick={() => {
                if (!activeSession || !selectedAssetId) {
                  return
                }
                void approve(activeSession.id, selectedAssetId, 'Approved in Review Studio')
              }}
            >
              Approve
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                if (!activeSession || !selectedAssetId) {
                  return
                }
                void reject(activeSession.id, selectedAssetId, 'Changes requested')
              }}
            >
              Request Changes
            </Button>
            <Button
              onClick={() => {
                if (!activeSession || !selectedAssetId) {
                  return
                }
                void publish(activeSession.id, selectedAssetId)
              }}
            >
              Publish Version
            </Button>
          </div>

          <div className="rounded border border-slate-700 bg-slate-950 p-3">
            <label className="mb-2 block text-xs uppercase tracking-widest text-slate-500">Comment Thread</label>
            <textarea
              className="min-h-28 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              value={commentDraft}
              onChange={(event) => setCommentDraft(event.target.value)}
              placeholder="Leave a review comment..."
            />
            <div className="mt-3 flex justify-end">
              <Button
                onClick={() => {
                  if (!activeSession || !commentDraft.trim()) {
                    return
                  }
                  void comment(activeSession.id, commentDraft)
                  setCommentDraft('')
                }}
              >
                Add Comment
              </Button>
            </div>
          </div>

          <div className="rounded border border-slate-700 bg-slate-950 p-3">
            <h4 className="text-sm font-medium text-slate-100">Review Timeline</h4>
            <ul className="mt-2 space-y-2 text-sm text-slate-300">
              {history.map((event) => (
                <li key={event.id} className="rounded bg-slate-900 px-3 py-2">
                  <div className="text-xs uppercase tracking-widest text-slate-500">{event.event_type}</div>
                  <div className="mt-1 text-slate-100">{event.comment ?? `${event.from_status ?? 'none'} -> ${event.to_status ?? 'none'}`}</div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Panel>

      <Panel title="Inspector" subtitle="Status, assets, history, and activity links">
        <div className="space-y-2 text-sm text-slate-300">
          <InspectorRow label="Review" value={activeSession?.title ?? 'None'} />
          <InspectorRow label="Status" value={activeSession?.status ?? 'None'} />
          <InspectorRow label="Source Asset" value={activeSession?.asset_id ?? 'None'} />
          <InspectorRow label="Published Asset" value={activeSession?.published_asset_id ?? 'Pending'} />
          <InspectorRow label="History Events" value={String(history.length)} />
          <InspectorRow label="Activity" value={activity[0]?.name ?? 'No activity yet'} />
          <InspectorRow label="Bottom Panel" value="Validation Checks · Publish Queue · Tasks" />
        </div>
      </Panel>
    </section>
  )
}

function InspectorRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-900 px-3 py-2">
      <div className="text-xs uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-1 text-slate-100">{value}</div>
    </div>
  )
}
