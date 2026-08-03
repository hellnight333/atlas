import { RouterProvider } from 'react-router-dom'

import { useBootstrapMockData } from '../hooks/useBootstrapMockData'
import { router } from './router'

/**
 * The application, once the kernel is up and setup is done.
 *
 * Nothing here may use a react-router hook. This component *provides* the
 * router, so it renders outside its own context — `useGlobalShortcuts` was
 * called here, it calls `useNavigate`, and that threw
 * "useNavigate() may be used only in the context of a <Router> component"
 * on every single render. React unmounts the tree when a render throws, so
 * the packaged app showed a permanently blank window with no error anywhere.
 *
 * Router-dependent hooks belong in `DesktopShellLayout`, which is the root
 * route element and therefore inside the router.
 */
export function App() {
  useBootstrapMockData()

  return <RouterProvider router={router} />
}
