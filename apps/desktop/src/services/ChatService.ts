import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  ChatConversation,
  ChatConversationRequest,
  ChatConversationUpdateRequest,
  ChatMessage,
  ChatMessageRequest,
} from '../api/types'

export interface ChatService {
  createConversation(request: ChatConversationRequest): Promise<ChatConversation>
  listConversations(projectId?: string): Promise<ChatConversation[]>
  getConversation(id: string): Promise<ChatConversation | undefined>
  sendMessage(request: ChatMessageRequest): Promise<ChatMessage>
  updateConversation(id: string, request: ChatConversationUpdateRequest): Promise<ChatConversation>
  deleteConversation(id: string): Promise<void>
}

export const chatService: ChatService = {
  async createConversation(request) {
    return getAtlasProvider().createChatConversation(request)
  },
  async listConversations(projectId) {
    return getAtlasProvider().listChatConversations(projectId)
  },
  async getConversation(id) {
    return getAtlasProvider().getChatConversation(id)
  },
  async sendMessage(request) {
    return getAtlasProvider().sendChatMessage(request)
  },
  async updateConversation(id, request) {
    return getAtlasProvider().updateChatConversation(id, request)
  },
  async deleteConversation(id) {
    return getAtlasProvider().deleteChatConversation(id)
  },
}