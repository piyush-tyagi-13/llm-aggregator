import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="flex min-h-screen items-center justify-center bg-slate-950 p-8">
            <div className="max-w-lg rounded-lg border border-red-800/40 bg-red-950/40 p-6 text-center">
              <h2 className="mb-2 text-lg font-semibold text-red-300">
                Something went wrong
              </h2>
              <p className="mb-4 text-sm text-slate-400">
                {this.state.error?.message || 'An unexpected error occurred'}
              </p>
              <button
                className="rounded bg-red-800/60 px-4 py-2 text-sm text-white transition-colors hover:bg-red-700/60"
                onClick={() => this.setState({ hasError: false, error: null })}
              >
                Try again
              </button>
            </div>
          </div>
        )
      )
    }
    return this.props.children
  }
}
