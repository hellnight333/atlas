import { useEffect } from 'react'
import { isRouteErrorResponse, useRouteError } from 'react-router-dom'

import { logStartup } from '../api/shell'
import { StartupDiagnostics } from '../features/onboarding/StartupDiagnostics'

/**
 * What a route shows when it throws.
 *
 * `RouterProvider` has an error boundary of its own, and it catches route
 * errors *before* they can reach the application's boundary. Without an
 * `errorElement` the user gets react-router's developer fallback — a minified
 * stack and the words "Hey developer 👋" — while `RootErrorBoundary` never
 * fires and nothing is written to the startup log.
 *
 * That is how a crash inside the application looked like nothing at all: the
 * shell reported a healthy boot, the log ended at "rendering main application",
 * and the failure was visible only on screen, in a form aimed at whoever wrote
 * the code rather than whoever is trying to use it.
 */
export function RouteErrorScreen() {
  const error = useRouteError()

  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : String(error)

  const stack = error instanceof Error ? error.stack : undefined

  useEffect(() => {
    // Written where a user can find it and send it, rather than left in a
    // devtools console they have no way to open in a packaged app.
    logStartup(`route crash: ${message}`)
    if (stack) {
      logStartup(`route stack: ${stack.split('\n').slice(0, 12).join(' | ')}`)
    }
  }, [message, stack])

  return (
    <StartupDiagnostics
      stage="Rendering the workspace"
      reason={`Atlas started, but this screen failed to render: ${message}`}
      retryLabel="Reload"
      onRetry={() => window.location.reload()}
    />
  )
}
