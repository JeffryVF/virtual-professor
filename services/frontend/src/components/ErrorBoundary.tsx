'use client'

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

interface ErrorBoundaryProps {
  children: ReactNode
  fallback?: ReactNode
  onError?: (error: Error, info: ErrorInfo) => void
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (process.env.NODE_ENV === 'development') {
      console.error('[ErrorBoundary]', error, info)
    }
    this.props.onError?.(error, info)
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }

      return (
        <div className="flex items-center justify-center min-h-[300px]">
          <div className="flex flex-col items-center gap-4 rounded-lg border bg-card p-8 text-center shadow-sm max-w-md">
            <AlertTriangle className="h-12 w-12 text-destructive" />
            <div>
              <h2 className="text-lg font-semibold text-card-foreground">Algo sali&oacute; mal</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Ocurri&oacute; un error inesperado. Por favor intenta de nuevo.
              </p>
            </div>
            <button
              onClick={this.handleRetry}
              className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Reintentar
            </button>
            {process.env.NODE_ENV === 'development' && this.state.error && (
              <details className="w-full text-left">
                <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                  Ver detalle del error
                </summary>
                <pre className="mt-2 max-h-40 overflow-auto rounded bg-muted p-2 text-xs text-muted-foreground">
                  {this.state.error.stack}
                </pre>
              </details>
            )}
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
