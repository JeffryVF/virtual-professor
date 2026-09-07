'use client'

import { useCallback, useEffect, useState, useRef } from 'react'
import { RefreshCw, Activity, AlertCircle, CheckCircle, XCircle } from 'lucide-react'
import { handleApiError } from '@/lib/error-handler'
import { API_BASE } from '@/lib/api-base'

interface ServiceProbe {
  status: 'healthy' | 'degraded' | 'unhealthy'
  latency_ms: number | null
  error: string | null
}

/** Response shape from GET /health */
interface HealthResponse {
  status: 'healthy' | 'degraded'
  timestamp: string
  services: Record<string, ServiceProbe>
  version: string
}

type FetchState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'loaded'; data: HealthResponse }

const serviceNameLabels: Record<string, string> = {
  postgres: 'PostgreSQL',
  redis: 'Redis',
  qdrant: 'Qdrant',
  zai: 'Z.AI (GLM)',
  kokoro: 'Kokoro (TTS)',
  whisper: 'Whisper (STT)',
}

function StatusDot({ status }: { status: ServiceProbe['status'] }) {
  const colors: Record<ServiceProbe['status'], string> = {
    healthy: 'bg-green-500',
    degraded: 'bg-yellow-500',
    unhealthy: 'bg-red-500',
  }
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${colors[status]}`} aria-hidden />
}

function StatusBadge({ status }: { status: HealthResponse['status'] }) {
  if (status === 'healthy') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-800">
        <CheckCircle className="h-4 w-4" />
        Sistema Saludable
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-red-100 px-3 py-1 text-sm font-medium text-red-800">
      <XCircle className="h-4 w-4" />
      Sistema Degradado
    </span>
  )
}

function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-lg border bg-card p-5">
      <div className="mb-3 h-4 w-24 rounded bg-muted" />
      <div className="mb-2 h-3 w-16 rounded bg-muted" />
      <div className="h-3 w-12 rounded bg-muted" />
    </div>
  )
}

export default function AdminStatusPage() {
  const [state, setState] = useState<FetchState>({ kind: 'loading' })
  const [autoRefresh, setAutoRefresh] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchHealth = useCallback(async (showLoading = false) => {
    if (showLoading) {
      setState({ kind: 'loading' })
    }

    try {
      const res = await fetch(`${API_BASE}/health`)
      if (!res.ok) {
        const err = await handleApiError(res, { silent: true })
        setState({ kind: 'error', message: err.detail ?? err.message })
        return
      }
      const data = (await res.json()) as HealthResponse
      setState({ kind: 'loaded', data })
    } catch (err) {
      const apiErr = await handleApiError(err, { silent: true })
      setState({ kind: 'error', message: apiErr.message })
    }
  }, [])

  // Initial fetch
  useEffect(() => {
    fetchHealth(true)
  }, [fetchHealth])

  // Auto-refresh
  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(() => fetchHealth(false), 30_000)
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [autoRefresh, fetchHealth])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Estado del Sistema</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Monitoreo de servicios y dependencias
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={e => setAutoRefresh(e.target.checked)}
              className="rounded border-gray-300"
            />
            Auto-refresh (30s)
          </label>
          <button
            onClick={() => fetchHealth(true)}
            className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-sm font-medium hover:bg-accent transition-colors"
          >
            <RefreshCw className="h-4 w-4" />
            Refrescar
          </button>
        </div>
      </div>

      {state.kind === 'loading' && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {state.kind === 'error' && (
        <div className="flex flex-col items-center gap-3 rounded-lg border bg-card p-8 text-center">
          <AlertCircle className="h-10 w-10 text-destructive" />
          <div>
            <p className="font-medium">No se pudo obtener el estado</p>
            <p className="text-sm text-muted-foreground mt-1">{state.message}</p>
          </div>
          <button
            onClick={() => fetchHealth(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <RefreshCw className="h-4 w-4" />
            Reintentar
          </button>
        </div>
      )}

      {state.kind === 'loaded' && (
        <>
          <div className="flex flex-wrap items-center gap-4">
            <StatusBadge status={state.data.status} />
            <span className="text-sm text-muted-foreground">
              &Uacute;ltima verificaci&oacute;n:{' '}
               {new Date(state.data.timestamp).toLocaleString('es-CR')}
            </span>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(state.data.services).map(([name, probe]) => (
              <div
                key={name}
                className="rounded-lg border bg-card p-5 shadow-sm"
              >
                <div className="flex items-center gap-2 mb-3">
                  <Activity className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-medium text-sm">{serviceNameLabels[name] ?? name}</h3>
                </div>
                <div className="space-y-1.5 text-sm">
                  <div className="flex items-center gap-2">
                    <StatusDot status={probe.status} />
                    <span className="capitalize text-muted-foreground">
                      {probe.status === 'healthy'
                        ? 'Saludable'
                        : probe.status === 'degraded'
                          ? 'Degradado'
                          : 'No disponible'}
                    </span>
                  </div>
                  {probe.latency_ms !== null && (
                    <p className="text-muted-foreground">
                  Latencia: <span className="font-medium tabular-nums">{probe.latency_ms}ms</span>
                    </p>
                  )}
                  {probe.error && (
                    <p className="text-xs text-destructive">{probe.error}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
