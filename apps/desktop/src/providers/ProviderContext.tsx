import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react'

import { isDesktopShell } from '../api/runtime'
import type { AtlasProvider, ProviderMode } from '../api/types'
import { kernelProvider } from './KernelProvider'
import { mockProvider } from './MockProvider'

const atlasProviderContext = createContext<AtlasProvider>(mockProvider)

let activeProvider: AtlasProvider = mockProvider

function resolveProvider(mode: ProviderMode): AtlasProvider {
  if (mode === 'kernel-local' || mode === 'kernel-remote') {
    return kernelProvider
  }
  return mockProvider
}

/**
 * Which provider to use when nothing says otherwise.
 *
 * Inside the packaged desktop shell there is a real kernel running, started by
 * the app itself — defaulting to mock there would boot a healthy kernel and
 * then show the user invented data, which is worse than showing nothing. In a
 * browser with no kernel, mock remains the sensible default.
 */
function defaultMode(): ProviderMode {
  const configured = import.meta.env.VITE_ATLAS_PROVIDER as ProviderMode | undefined
  if (configured) return configured
  return isDesktopShell() ? 'kernel-local' : 'mock'
}

export function AtlasProviderContext({ children }: { children: ReactNode }) {
  const mode = defaultMode()
  const provider = useMemo(() => resolveProvider(mode), [mode])

  useEffect(() => {
    activeProvider = provider
  }, [provider])

  return <atlasProviderContext.Provider value={provider}>{children}</atlasProviderContext.Provider>
}

export function useAtlasProvider(): AtlasProvider {
  return useContext(atlasProviderContext)
}

export function getAtlasProvider(): AtlasProvider {
  return activeProvider
}
