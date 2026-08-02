import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './index.css'
import { App } from './app/App'
import { AtlasProviderContext } from './providers/ProviderContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AtlasProviderContext>
      <App />
    </AtlasProviderContext>
  </StrictMode>,
)
