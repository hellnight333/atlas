import { useEffect, useMemo, useState } from 'react'

import { Button, Panel } from '../../../components'
import { useActivityStore, useAssetStore, useMissionControlStore, useProjectStore } from '../../../stores'
import { useChatStore } from '../../../stores/chatStore'

export function ChatStudioScreen() {
  const projects = useProjectStore((state) => state.projects)
  const selectedProject = projects[0]
  const conversations = useChatStore((state) => state.conversations)
  const activeConversation = useChatStore((state) => state.activeConversation)
  const messages = useChatStore((state) => state.messages)
  const loadConversations = useChatStore((state) => state.loadConversations)
  const createConversation = useChatStore((state) => state.createConversation)
  const openConversation = useChatStore((state) => state.openConversation)
  const sendMessage = useChatStore((state) => state.sendMessage)
  const updateConversation = useChatStore((state) => state.updateConversation)
  const deleteConversation = useChatStore((state) => state.deleteConversation)
  const pinConversation = useChatStore((state) => state.pinConversation)
  const activity = useActivityStore((state) => state.jobs)
  const assets = useAssetStore((state) => state.assets)
  const setMissionControlOpen = useMissionControlStore((state) => state.setOpen)

  const [prompt, setPrompt] = useState('')
  const [draftTitle, setDraftTitle] = useState('New Conversation')

  useEffect(() => {
    if (selectedProject) {
      void loadConversations(selectedProject.id)
    }
  }, [loadConversations, selectedProject])

  const conversationMetadata = useMemo(() => {
    return activeConversation
      ? [
          ['Provider', activeConversation.provider_name ?? 'Pending'],
          ['Execution', activeConversation.execution_time_ms ? `${activeConversation.execution_time_ms} ms` : 'Pending'],
          ['Tokens', activeConversation.tokens ? String(activeConversation.tokens) : 'Pending'],
          ['Workflow', activeConversation.workflow_id ?? 'Chat Studio workflow'],
          ['Prompt Version', String(activeConversation.prompt_version)],
          ['Response Version', String(activeConversation.response_version)],
          ['Parent Conversation', activeConversation.parent_conversation_id ?? 'None'],
        ]
      : []
  }, [activeConversation])

  return (
    <section className="grid flex-1 gap-4 p-4 xl:grid-cols-[280px_minmax(0,1fr)_320px]">
      <Panel title="Conversation List" subtitle="Persistent project conversations">
        <div className="space-y-3">
          <div className="space-y-2">
            <input
              className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              placeholder="Conversation title"
            />
            <Button
              onClick={() => {
                if (!selectedProject) {
                  return
                }
                void createConversation({ projectId: selectedProject.id, title: draftTitle })
              }}
            >
              New Conversation
            </Button>
          </div>
          <div className="space-y-2">
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                className={`block w-full rounded px-3 py-2 text-left text-sm ${activeConversation?.id === conversation.id ? 'bg-cyan-500/15 text-cyan-100' : 'bg-slate-900 text-slate-300 hover:bg-slate-800'}`}
                onClick={() => void openConversation(conversation.id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{conversation.title}</span>
                  {conversation.pinned ? <span className="text-xs text-cyan-300">Pinned</span> : null}
                </div>
                <p className="mt-1 text-xs text-slate-500">{conversation.project_id}</p>
              </button>
            ))}
          </div>
        </div>
      </Panel>

      <Panel title="Conversation View" subtitle="Prompt box, streaming placeholder, response rendering">
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setMissionControlOpen(true)}>Open Mission Control</Button>
            <Button
              variant="ghost"
              onClick={() => {
                if (activeConversation) {
                  void pinConversation(activeConversation.id, !activeConversation.pinned)
                }
              }}
            >
              {activeConversation?.pinned ? 'Unpin' : 'Pin'} Conversation
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                if (activeConversation) {
                  void updateConversation(activeConversation.id, { title: `${activeConversation.title} · Renamed` })
                }
              }}
            >
              Rename
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                if (activeConversation) {
                  void deleteConversation(activeConversation.id)
                }
              }}
            >
              Delete
            </Button>
          </div>

          <div className="rounded border border-slate-700 bg-slate-950 p-3">
            <label className="mb-2 block text-xs uppercase tracking-widest text-slate-500">Prompt Box</label>
            <textarea
              className="min-h-36 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Write a prompt for the selected project..."
            />
            <div className="mt-3 flex items-center justify-between gap-2">
              <span className="text-xs text-slate-500">Streaming placeholder active</span>
              <Button
                variant="accent"
                onClick={() => {
                  if (!activeConversation || !prompt.trim()) {
                    return
                  }
                  void sendMessage({
                    conversationId: activeConversation.id,
                    role: 'user',
                    content: prompt,
                    metadata: { source: 'desktop-chat-studio' },
                  })
                  void sendMessage({
                    conversationId: activeConversation.id,
                    role: 'assistant',
                    content: `Response for: ${prompt}`,
                    providerName: 'local-text',
                    executionTimeMs: 420,
                    tokens: prompt.split(/\s+/).filter(Boolean).length * 8,
                    metadata: { source: 'mock-stream' },
                  })
                  setPrompt('')
                }}
              >
                Send
              </Button>
            </div>
          </div>

          <div className="space-y-3">
            {messages.map((message) => (
              <div key={message.id} className={`rounded border px-3 py-2 text-sm ${message.role === 'user' ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-50' : 'border-slate-700 bg-slate-900 text-slate-200'}`}>
                <div className="mb-1 flex items-center justify-between text-xs uppercase tracking-widest text-slate-500">
                  <span>{message.role}</span>
                  <span>v{message.version}</span>
                </div>
                <p>{message.content}</p>
              </div>
            ))}
          </div>
        </div>
      </Panel>

      <Panel title="Inspector" subtitle="Metadata, relationships, and execution traces">
        <div className="space-y-2 text-sm text-slate-300">
          {conversationMetadata.map(([label, value]) => (
            <div key={label} className="rounded bg-slate-900 px-3 py-2">
              <div className="text-xs uppercase tracking-widest text-slate-500">{label}</div>
              <div className="mt-1 text-slate-100">{value}</div>
            </div>
          ))}
          <div className="rounded bg-slate-900 px-3 py-2">
            <div className="text-xs uppercase tracking-widest text-slate-500">Activity Link</div>
            <div className="mt-1 text-slate-100">{activity[0]?.name ?? 'No activity yet'}</div>
          </div>
          <div className="rounded bg-slate-900 px-3 py-2">
            <div className="text-xs uppercase tracking-widest text-slate-500">Asset Link</div>
            <div className="mt-1 text-slate-100">{assets[0]?.title ?? 'No assets yet'}</div>
          </div>
        </div>
      </Panel>
    </section>
  )
}