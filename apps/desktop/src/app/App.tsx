import { RouterProvider } from 'react-router-dom'

import { useBootstrapMockData } from '../hooks/useBootstrapMockData'
import { useGlobalShortcuts } from '../hooks/useGlobalShortcuts'
import { router } from './router'

export function App() {
  useBootstrapMockData()
  useGlobalShortcuts()

  return <RouterProvider router={router} />
}
