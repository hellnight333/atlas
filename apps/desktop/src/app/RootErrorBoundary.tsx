import { Component, type ErrorInfo, type ReactNode } from 'react'

import { logStartup } from '../api/shell'
import { StartupDiagnostics } from '../features/onboarding/StartupDiagnostics'

/**
 * The floor under the entire application.
 *
 * React unmounts the whole tree when a render throws. Without a boundary the
 * result is an empty document — a black window, no message, nothing in any log,
 * and no way for the user to tell a crash from a hang. RC1 shipped exactly that
 * (`useNavigate` was called outside the router, so every render threw), and it
 * looked identical to the kernel failing to start.
 *
 * This exists so that class of bug can never again present as a blank screen.
 * It is a safety net and not an excuse: a crash that lands here is still a bug.
 */

type Props = { children: ReactNode }
type State = { error: Error | null }

export class RootErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Written to logs/startup.log, which is what a user can actually send.
    // The component stack is the useful half — it names the screen.
    logStartup(`render crash: ${error.message}`)
    const stack = info.componentStack?.trim().split('\n').slice(0, 8).join(' | ')
    if (stack) logStartup(`component stack: ${stack}`)
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <StartupDiagnostics
        stage="Rendering the application"
        reason={`Atlas started, but the interface failed to render: ${error.message}`}
        retryLabel="Reload"
        onRetry={() => window.location.reload()}
      />
    )
  }
}
