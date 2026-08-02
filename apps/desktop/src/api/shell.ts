/**
 * Bridge to the Tauri shell.
 *
 * Only meaningful in a packaged build. In a browser every function here
 * resolves to a benign default, so the same code runs in `npm run dev`
 * without branching at every call site.
 *
 * Tauri APIs are imported dynamically. A static import would put the module in
 * the browser bundle too, where `window.__TAURI_INTERNALS__` does not exist
 * and the import throws at load time.
 */

import { isDesktopShell, setRuntimeBaseUrl } from './runtime'

export type BootstrapStage =
  | 'starting'
  | 'preparing_storage'
  | 'initialising_database'
  | 'starting_database'
  | 'starting_kernel'
  | 'waiting_for_kernel'
  | 'ready'
  | 'failed'

export interface BootstrapProgress {
  stage: BootstrapStage
  message: string
  /** True only on the run that creates the data directory. */
  first_run: boolean
  detail: string | null
}

export interface BackendInfo {
  api_port: number | null
  api_base_url: string | null
  version: string
}

/** Progress shown before the shell has reported anything. */
export const INITIAL_PROGRESS: BootstrapProgress = {
  stage: 'starting',
  message: 'Starting Atlas',
  first_run: false,
  detail: null,
}

/** In a browser the kernel is assumed already running; nothing to report. */
export const BROWSER_PROGRESS: BootstrapProgress = {
  stage: 'ready',
  message: 'Connected',
  first_run: false,
  detail: null,
}

async function invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke: tauriInvoke } = await import('@tauri-apps/api/core')
  return tauriInvoke<T>(command, args)
}

/** Ask the shell where the kernel is, and remember it for every client. */
export async function resolveBackend(): Promise<BackendInfo | null> {
  if (!isDesktopShell()) return null
  try {
    const info = await invoke<BackendInfo>('backend')
    if (info.api_base_url) {
      setRuntimeBaseUrl(info.api_base_url)
    }
    return info
  } catch {
    // The shell is present but not answering yet. The caller retries via the
    // bootstrap event rather than failing outright.
    return null
  }
}

/** The current boot stage, for a UI that mounted after events were emitted. */
export async function currentProgress(): Promise<BootstrapProgress> {
  if (!isDesktopShell()) return BROWSER_PROGRESS
  try {
    const progress = await invoke<BootstrapProgress | null>('bootstrap_progress')
    return progress ?? INITIAL_PROGRESS
  } catch {
    return INITIAL_PROGRESS
  }
}

/**
 * Subscribe to boot progress. Returns an unsubscribe function.
 *
 * When the stage reaches `ready` the backend URL is resolved before the
 * callback fires, so a listener that starts loading data on `ready` is
 * guaranteed a usable base URL.
 */
export async function onBootstrapProgress(
  handler: (progress: BootstrapProgress) => void,
): Promise<() => void> {
  if (!isDesktopShell()) {
    handler(BROWSER_PROGRESS)
    return () => {}
  }

  const { listen } = await import('@tauri-apps/api/event')
  const unlisten = await listen<BootstrapProgress>('atlas://bootstrap', async (event) => {
    if (event.payload.stage === 'ready') {
      await resolveBackend()
    }
    handler(event.payload)
  })

  // Cover the race where bootstrap finished before this listener attached.
  const existing = await currentProgress()
  if (existing.stage === 'ready') {
    await resolveBackend()
  }
  handler(existing)

  return unlisten
}

/** Tail of the PostgreSQL log, for the troubleshooting panel. */
export async function databaseLog(lines = 200): Promise<string | null> {
  if (!isDesktopShell()) return null
  try {
    return await invoke<string | null>('database_log', { lines })
  } catch {
    return null
  }
}

/** Open a URL in the user's real browser rather than inside the app window. */
export async function openExternal(url: string): Promise<void> {
  if (!isDesktopShell()) {
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  const { openUrl } = await import('@tauri-apps/plugin-opener')
  await openUrl(url)
}
