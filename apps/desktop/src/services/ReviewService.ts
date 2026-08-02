import { getAtlasProvider } from '../providers/ProviderContext'
import type {
  ReviewComment,
  ReviewCommentRequest,
  ReviewDecisionRequest,
  ReviewHistoryEvent,
  ReviewPublishRequest,
  ReviewSession,
  ReviewSessionRequest,
} from '../api/types'

export interface ReviewService {
  createSession(request: ReviewSessionRequest): Promise<ReviewSession>
  listSessions(projectId?: string): Promise<ReviewSession[]>
  approve(reviewId: string, request: ReviewDecisionRequest): Promise<ReviewSession>
  reject(reviewId: string, request: ReviewDecisionRequest): Promise<ReviewSession>
  comment(reviewId: string, request: ReviewCommentRequest): Promise<ReviewComment>
  publish(reviewId: string, request: ReviewPublishRequest): Promise<Record<string, unknown>>
  history(reviewId: string): Promise<ReviewHistoryEvent[]>
}

export const reviewService: ReviewService = {
  async createSession(request) {
    return getAtlasProvider().createReviewSession(request)
  },
  async listSessions(projectId) {
    return getAtlasProvider().listReviewSessions(projectId)
  },
  async approve(reviewId, request) {
    return getAtlasProvider().approveReview(reviewId, request)
  },
  async reject(reviewId, request) {
    return getAtlasProvider().rejectReview(reviewId, request)
  },
  async comment(reviewId, request) {
    return getAtlasProvider().commentReview(reviewId, request)
  },
  async publish(reviewId, request) {
    return getAtlasProvider().publishReview(reviewId, request)
  },
  async history(reviewId) {
    return getAtlasProvider().getReviewHistory(reviewId)
  },
}