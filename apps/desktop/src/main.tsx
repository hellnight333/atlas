import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './index.css'
import { logStartup } from './api/shell'
import { AppGate } from './app/AppGate'
import { RootErrorBoundary } from './app/RootErrorBoundary'
import { AtlasProviderContext } from './providers/ProviderContext'

// The first thing the webview does that the shell can see. If startup.log ends
// here, the bundle loaded but React never mounted; if it never appears, the
// webview itself never ran the bundle.
logStartup('webview bundle loaded')

// A script error after this point would otherwise leave a blank window with the
// reason only in a devtools console the user cannot open.
window.addEventListener('error', (event) => {
  logStartup(`uncaught error: ${event.message} (${event.filename}:${event.lineno})`)
})
window.addEventListener('unhandledrejection', (event) => {
  logStartup(`unhandled rejection: ${String(event.reason)}`)
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RootErrorBoundary>
      <AtlasProviderContext>
        <AppGate />
      </AtlasProviderContext>
    </RootErrorBoundary>
  </StrictMode>,
)
