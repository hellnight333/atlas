import type { ApiError, ResourceState } from '../api/types'

export function createResourceState<T>(data: T): ResourceState<T> {
  return {
    data,
    status: 'idle',
    error: null,
    lastLoadedAt: null,
  }
}

export function toApiError(error: unknown): ApiError {
  if (typeof error === 'object' && error !== null && 'code' in error && 'message' in error && 'retryable' in error) {
    return error as ApiError
  }

  return {
    code: 'UNKNOWN',
    message: error instanceof Error ? error.message : 'Unknown Atlas provider error.',
    retryable: true,
    cause: error,
  }
}
