import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './index.css'
import { AppGate } from './app/AppGate'
import { AtlasProviderContext } from './providers/ProviderContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AtlasProviderContext>
      <AppGate />
    </AtlasProviderContext>
  </StrictMode>,
)
