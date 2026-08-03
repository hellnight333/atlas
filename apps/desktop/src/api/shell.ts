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
      logStartup(`api base url resolved: ${info.api_base_url}`)
    } else {
      // Every later request would go to the webview's own origin and 404.
      logStartup('api base url is still null; the shell has no kernel port yet')
    }
    return info
  } catch (error) {
    // The shell is present but not answering yet. The caller retries via the
    // bootstrap event rather than failing outright.
    logStartup(`could not ask the shell for the kernel port: ${String(error)}`)
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

/**
 * Write a line into the same `logs/startup.log` the shell writes to.
 *
 * The shell can only record what it does itself; it cannot see whether the
 * window ever rendered. Without these lines the log ends at "kernel: ready"
 * and says nothing about the half of startup that was actually failing.
 *
 * Never throws and never blocks the caller — a diagnostic that can break the
 * boot it is diagnosing is worse than no diagnostic.
 */
export function logStartup(message: string): void {
  if (!isDesktopShell()) return
  void invoke('log_startup', { message }).catch(() => {})
}

/** Tail of `logs/startup.log`. */
export async function startupLog(lines = 300): Promise<string | null> {
  if (!isDesktopShell()) return null
  try {
    return await invoke<string | null>('startup_log', { lines })
  } catch {
    return null
  }
}

/** Everything worth sending when Atlas will not start. */
export async function diagnosticReport(): Promise<string> {
  if (!isDesktopShell()) return 'Atlas is running in a browser; there is no shell to report on.'
  try {
    return await invoke<string>('diagnostic_report')
  } catch (error) {
    return `Could not assemble a diagnostic report: ${String(error)}`
  }
}

/** Reveal the log directory in the user's file manager. */
export async function openLogFolder(): Promise<void> {
  if (!isDesktopShell()) return
  await invoke('open_log_folder')
}

/** Move a damaged database aside and start over. Destructive; ask first. */
export async function resetDatabase(): Promise<string> {
  if (!isDesktopShell()) return ''
  return invoke<string>('reset_database')
}

/** Run the boot sequence again after a failure. */
export async function retryBootstrap(): Promise<void> {
  if (!isDesktopShell()) return
  await invoke('retry_bootstrap')
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
