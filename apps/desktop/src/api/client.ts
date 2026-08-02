import type { ApiError } from './types'

export class AtlasApiClient {
  private readonly baseUrl: string

  constructor(baseUrl = import.meta.env.VITE_ATLAS_API_BASE_URL ?? '') {
    this.baseUrl = baseUrl
  }

  async get<T>(path: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`)
    if (!response.ok) {
      throw this.createNetworkPlaceholder(await safeErrorPayload(response))
    }
    return (await response.json()) as T
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      body: body instanceof FormData ? body : JSON.stringify(body ?? {}),
      headers: body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    })
    if (!response.ok) {
      throw this.createNetworkPlaceholder(await safeErrorPayload(response))
    }
    return (await response.json()) as T
  }

  async put<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'PUT',
      body: JSON.stringify(body ?? {}),
      headers: { 'Content-Type': 'application/json' },
    })
    if (!response.ok) {
      throw this.createNetworkPlaceholder(await safeErrorPayload(response))
    }
    return (await response.json()) as T
  }

  async patch<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'PATCH',
      body: JSON.stringify(body ?? {}),
      headers: { 'Content-Type': 'application/json' },
    })
    if (!response.ok) {
      throw this.createNetworkPlaceholder(await safeErrorPayload(response))
    }
    return (await response.json()) as T
  }

  async delete(path: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: 'DELETE',
    })
    if (!response.ok) {
      throw this.createNetworkPlaceholder(await safeErrorPayload(response))
    }
  }

  createNotImplementedError(method: 'GET' | 'POST'): ApiError {
    return {
      code: 'NOT_IMPLEMENTED',
      message: `Atlas API client ${method} transport is not connected yet.`,
      retryable: false,
    }
  }

  createOfflinePlaceholder(cause?: unknown): ApiError {
    return {
      code: 'OFFLINE',
      message: 'Atlas provider is offline. Display offline placeholder state.',
      retryable: true,
      cause,
    }
  }

  createNetworkPlaceholder(cause?: unknown): ApiError {
    return {
      code: 'NETWORK_UNAVAILABLE',
      message: 'Atlas network connection is unavailable. Display network placeholder state.',
      retryable: true,
      cause,
    }
  }
}

async function safeErrorPayload(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return response.statusText
  }
}

export async function withRetry<T>(fn: () => Promise<T>, retries = 1): Promise<T> {
  let lastError: unknown

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await fn()
    } catch (error) {
      lastError = error
    }
  }

  throw lastError
}
