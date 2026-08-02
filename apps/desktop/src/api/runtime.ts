/**
 * Where the kernel actually is, decided at runtime.
 *
 * In development the kernel is on a known port and `VITE_ATLAS_API_BASE_URL`
 * is enough. In a packaged build the port is chosen when Atlas starts — two
 * copies must not fight over 8000 — so the shell tells the frontend after the
 * kernel is up.
 *
 * Resolution order, highest first:
 *   1. a base URL passed explicitly to AtlasApiClient
 *   2. the runtime value set here by the Tauri shell
 *   3. VITE_ATLAS_API_BASE_URL from the build
 *   4. same-origin
 */

let runtimeBaseUrl: string | null = null

export function setRuntimeBaseUrl(url: string): void {
  runtimeBaseUrl = url.replace(/\/$/, '')
}

export function getRuntimeBaseUrl(): string | null {
  return runtimeBaseUrl
}

export function clearRuntimeBaseUrl(): void {
  runtimeBaseUrl = null
}

/** True when running inside the Tauri shell rather than a browser tab. */
export function isDesktopShell(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}
