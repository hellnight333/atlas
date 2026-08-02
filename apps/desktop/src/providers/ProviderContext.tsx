import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react'

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

export function AtlasProviderContext({ children }: { children: ReactNode }) {
  const mode = ((import.meta.env.VITE_ATLAS_PROVIDER as ProviderMode | undefined) ?? 'mock')
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
