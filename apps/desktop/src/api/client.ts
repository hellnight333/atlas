import { getRuntimeBaseUrl } from './runtime'
import type { ApiError } from './types'

export class AtlasApiClient {
  private readonly explicitBaseUrl: string | undefined

  constructor(baseUrl?: string) {
    this.explicitBaseUrl = baseUrl
  }

  /**
   * Resolved per request, not once at construction.
   *
   * A packaged Atlas does not know its own port until the kernel has started,
   * and clients are constructed before that happens. Reading the value lazily
   * is what lets the same client work in both dev and a packaged build.
   */
  private get baseUrl(): string {
    return this.explicitBaseUrl ?? getRuntimeBaseUrl() ?? import.meta.env.VITE_ATLAS_API_BASE_URL ?? ''
  }

  /**
   * A fetch that is guaranteed to settle.
   *
   * Without a deadline, a request to a kernel that has bound its port but is
   * not yet serving never resolves and never rejects. The caller's promise
   * stays pending forever, and any UI waiting on it — the boot gate, in
   * practice — sits on a blank screen with no error to report.
   *
   * No timeout is applied unless one is asked for, because some calls
   * legitimately run for minutes.
   */
  private async send(path: string, init: RequestInit, timeoutMs?: number): Promise<Response> {
    if (!timeoutMs) return fetch(`${this.baseUrl}${path}`, init)

    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      return await fetch(`${this.baseUrl}${path}`, { ...init, signal: controller.signal })
    } catch (error) {
      if (controller.signal.aborted) {
        throw new Error(`${path} did not respond within ${Math.round(timeoutMs / 1000)}s`)
      }
      throw error
    } finally {
      clearTimeout(timer)
    }
  }

  async get<T>(path: string, timeoutMs?: number): Promise<T> {
    const response = await this.send(path, {}, timeoutMs)
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
