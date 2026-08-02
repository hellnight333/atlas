import { create } from 'zustand'

import type { ApiError, ApiStatus, ChatConversation, ChatConversationRequest, ChatMessage, ChatMessageRequest } from '../api/types'
import { chatService } from '../services/ChatService'
import { toApiError } from '../services/types'

type ChatStore = {
  conversations: ChatConversation[]
  activeConversation: ChatConversation | null
  messages: ChatMessage[]
  status: ApiStatus
  error: ApiError | null
  loadConversations: (projectId?: string) => Promise<void>
  createConversation: (request: ChatConversationRequest) => Promise<ChatConversation | null>
  openConversation: (conversationId: string) => Promise<void>
  sendMessage: (request: ChatMessageRequest) => Promise<ChatMessage | null>
  updateConversation: (conversationId: string, request: Partial<ChatConversation>) => Promise<ChatConversation | null>
  deleteConversation: (conversationId: string) => Promise<void>
  pinConversation: (conversationId: string, pinned: boolean) => Promise<void>
}

export const useChatStore = create<ChatStore>((set, get) => ({
  conversations: [],
  activeConversation: null,
  messages: [],
  status: 'idle',
  error: null,
  loadConversations: async (projectId) => {
    set({ status: 'loading', error: null })
    try {
      const conversations = await chatService.listConversations(projectId)
      set({ conversations, status: conversations.length === 0 ? 'empty' : 'success', error: null })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  createConversation: async (request) => {
    set({ status: 'refreshing', error: null })
    try {
      const created = await chatService.createConversation(request)
      set((state) => ({ conversations: [created, ...state.conversations], activeConversation: created, messages: [], status: 'success', error: null }))
      return created
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  openConversation: async (conversationId) => {
    set({ status: 'loading', error: null })
    try {
      const conversation = await chatService.getConversation(conversationId)
      set({
        activeConversation: conversation ?? null,
        messages: conversation?.messages ?? [],
        status: conversation ? 'success' : 'empty',
        error: null,
      })
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  sendMessage: async (request) => {
    set({ status: 'refreshing', error: null })
    try {
      const message = await chatService.sendMessage(request)
      set((state) => ({
        messages: [...state.messages, message],
        activeConversation: state.activeConversation
          ? {
              ...state.activeConversation,
              prompt_version: request.role === 'user' ? state.activeConversation.prompt_version + 1 : state.activeConversation.prompt_version,
              response_version: request.role === 'assistant' ? state.activeConversation.response_version + 1 : state.activeConversation.response_version,
              provider_name: request.providerName ?? state.activeConversation.provider_name,
              execution_time_ms: request.executionTimeMs ?? state.activeConversation.execution_time_ms,
              tokens: request.tokens ?? state.activeConversation.tokens,
              prompt_asset_id: request.promptAssetId ?? state.activeConversation.prompt_asset_id,
              response_asset_id: request.responseAssetId ?? state.activeConversation.response_asset_id,
              updated_at: new Date().toISOString(),
            }
          : null,
        status: 'success',
        error: null,
      }))
      return message
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  updateConversation: async (conversationId, request) => {
    set({ status: 'refreshing', error: null })
    try {
      const existing = get().conversations.find((conversation) => conversation.id === conversationId) ?? get().activeConversation
      if (!existing) {
        throw new Error('Conversation not found')
      }
      const updated = await chatService.updateConversation(conversationId, {
        title: request.title,
        pinned: request.pinned,
        providerName: request.provider_name,
        executionTimeMs: request.execution_time_ms,
        tokens: request.tokens,
        workflowId: request.workflow_id,
        parentConversationId: request.parent_conversation_id,
        promptAssetId: request.prompt_asset_id,
        responseAssetId: request.response_asset_id,
        metadata: request.metadata,
      })
      set((state) => ({
        conversations: state.conversations.map((conversation) => (conversation.id === conversationId ? updated : conversation)),
        activeConversation: state.activeConversation?.id === conversationId ? updated : state.activeConversation,
        status: 'success',
        error: null,
      }))
      return updated
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
      return null
    }
  },
  deleteConversation: async (conversationId) => {
    set({ status: 'refreshing', error: null })
    try {
      await chatService.deleteConversation(conversationId)
      set((state) => ({
        conversations: state.conversations.filter((conversation) => conversation.id !== conversationId),
        activeConversation: state.activeConversation?.id === conversationId ? null : state.activeConversation,
        messages: state.activeConversation?.id === conversationId ? [] : state.messages,
        status: 'success',
        error: null,
      }))
    } catch (error) {
      set({ status: 'error', error: toApiError(error) })
    }
  },
  pinConversation: async (conversationId, pinned) => {
    const conversation = get().conversations.find((item) => item.id === conversationId)
    if (!conversation) {
      return
    }
    await get().updateConversation(conversationId, { ...conversation, pinned })
  },
}))