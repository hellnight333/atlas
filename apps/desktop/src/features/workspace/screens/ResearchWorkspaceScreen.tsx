import { useEffect, useMemo, useState } from 'react'

import { Button, Panel } from '../../../components'
import { useAssetStore, useProjectStore, useResearchStore } from '../../../stores'

export function ResearchWorkspaceScreen() {
  const projects = useProjectStore((state) => state.projects)
  const project = projects[0]
  const createSession = useResearchStore((state) => state.createSession)
  const sessions = useResearchStore((state) => state.sessions)
  const activeSession = useResearchStore((state) => state.activeSession)
  const sources = useResearchStore((state) => state.sources)
  const findings = useResearchStore((state) => state.findings)
  const report = useResearchStore((state) => state.report)
  const graph = useResearchStore((state) => state.graph)
  const search = useResearchStore((state) => state.search)
  const summarize = useResearchStore((state) => state.summarize)
  const generateReport = useResearchStore((state) => state.generateReport)
  const loadGraph = useResearchStore((state) => state.loadGraph)
  const loadSessions = useResearchStore((state) => state.loadSessions)
  const assets = useAssetStore((state) => state.assets)

  const [question, setQuestion] = useState('What does this project need next?')
  const [query, setQuery] = useState('Atlas project research')

  const sourceAssetIds = useMemo(
    () => sources.map((source) => String(source.id)).filter(Boolean),
    [sources],
  )

  useEffect(() => {
    if (!project) {
      return
    }
    void loadSessions(project.id)
    void loadGraph(project.id)
  }, [loadGraph, loadSessions, project])

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[280px_minmax(0,1fr)_320px]">
      <Panel title="Research Sessions" subtitle="Sessions, collections, sources, bookmarks">
        <div className="space-y-3">
          <textarea
            className="min-h-24 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <Button
            onClick={() => {
              if (!project) return
              void createSession(project.id, 'Research Session 001', question)
              void loadGraph(project.id)
            }}
          >
            Create Research Session
          </Button>
          <div className="rounded bg-slate-900 px-3 py-2 text-sm text-slate-300">
            <div className="text-xs uppercase tracking-widest text-slate-500">Active Session</div>
            <div className="mt-1 text-slate-100">{activeSession?.title ?? 'None'}</div>
          </div>
          <div className="space-y-2">
            {sessions.map((session) => (
              <div key={session.id} className="rounded bg-slate-900 px-3 py-2 text-sm text-slate-300">
                <div className="font-medium text-slate-100">{session.title}</div>
                <div className="mt-1 text-xs text-slate-500">{session.question}</div>
              </div>
            ))}
          </div>
          <div className="rounded bg-slate-900 px-3 py-2 text-sm text-slate-300">
            <div className="text-xs uppercase tracking-widest text-slate-500">Collections</div>
            <div className="mt-1">Collection asset placeholder</div>
          </div>
          <div className="rounded bg-slate-900 px-3 py-2 text-sm text-slate-300">
            <div className="text-xs uppercase tracking-widest text-slate-500">Bookmarks</div>
            <div className="mt-1">Bookmark placeholder</div>
          </div>
        </div>
      </Panel>

      <Panel title="Research Workspace" subtitle="Conversation, findings, notes, knowledge graph, source viewer">
        <div className="space-y-4">
          <div className="rounded border border-slate-700 bg-slate-950 p-3">
            <label className="mb-2 block text-xs uppercase tracking-widest text-slate-500">Search Sources</label>
            <input
              className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                onClick={() => {
                  if (!activeSession) return
                  void search(activeSession.id, query, 'mock-search')
                }}
              >
                Search Sources
              </Button>
              <Button
                variant="accent"
                onClick={() => {
                  if (!activeSession) return
                  void summarize(activeSession.id, sourceAssetIds, `Summarize findings for ${query}`)
                }}
              >
                Summarize
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  if (!activeSession) return
                  void generateReport(activeSession.id, 'markdown')
                }}
              >
                Generate Report
              </Button>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Subpanel title="Sources">
              <List items={sources.map((source) => String((source.metadata as Record<string, unknown> | undefined)?.title ?? source.id))} />
            </Subpanel>
            <Subpanel title="Findings">
              <List items={findings.map((finding) => String((finding.metadata as Record<string, unknown> | undefined)?.content ?? finding.id))} />
            </Subpanel>
            <Subpanel title="Knowledge Graph">
              <List items={(graph?.nodes ?? []).map((node) => `${node.type}: ${node.label}`)} />
            </Subpanel>
            <Subpanel title="Source Viewer">
              <List items={assets.slice(0, 5).map((asset) => asset.title)} />
            </Subpanel>
          </div>
        </div>
      </Panel>

      <Panel title="Inspector" subtitle="Metadata, citations, related assets, conversations, versions">
        <div className="space-y-2 text-sm text-slate-300">
          <InspectorRow label="Session" value={activeSession?.title ?? 'None'} />
          <InspectorRow label="Question" value={activeSession?.question ?? 'None'} />
          <InspectorRow label="Citation Count" value={String(sourceAssetIds.length)} />
          <InspectorRow label="Related Findings" value={String(findings.length)} />
          <InspectorRow label="Related Assets" value={String(assets.length)} />
          <InspectorRow label="Related Conversations" value={activeSession?.conversation_id ?? 'None'} />
          <InspectorRow label="Version History" value={report ? 'Report v1' : 'Pending'} />
          <InspectorRow label="Bottom Panel" value="Running Searches · Imports · AI Tasks" />
        </div>
      </Panel>
    </section>
  )
}

function Subpanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded border border-slate-800 bg-slate-950/80 p-3">
      <h4 className="text-sm font-medium text-slate-100">{title}</h4>
      <div className="mt-2">{children}</div>
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

function List({ items }: { items: string[] }) {
  return (
    <ul className="space-y-1 text-sm text-slate-300">
      {items.map((item) => (
        <li key={item} className="rounded bg-slate-900 px-2 py-1">
          {item}
        </li>
      ))}
    </ul>
  )
}
