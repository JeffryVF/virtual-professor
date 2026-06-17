'use client'
import { useEffect, useState, useCallback, useRef } from 'react'
import Link from 'next/link'
import { Loader2, RefreshCw, FileText, AlertCircle, Eye } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { getIndexingStatus, type CollectionStatus, type IndexingStatusResponse } from '@/lib/api'

export default function AdminDocumentsPage() {
  const [data, setData] = useState<IndexingStatusResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      setData(await getIndexingStatus())
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(load, 30_000)
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [autoRefresh, load])

  const statusBadge = (col: CollectionStatus) => {
    if (col.last_error) return <Badge variant="destructive">Error</Badge>
    if (col.total_documents === 0) return <Badge variant="secondary">Sin documentos</Badge>
    return col.qdrant_points > 0 ? <Badge variant="success">Indexado</Badge> : <Badge variant="warning">Pendiente</Badge>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Documentos</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Estado de indexación y documentos por profesor
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded"
            />
            Auto-refresh (30s)
          </label>
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={loading ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
          </Button>
        </div>
      </div>

      {/* Summary stats */}
      {data && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs text-muted-foreground">Profesores</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{data.summary.total_collections}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs text-muted-foreground">Documentos</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{data.summary.total_documents}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs text-muted-foreground">Chunks</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{data.summary.total_chunks}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs text-muted-foreground">Con errores</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold flex items-center gap-2">
                {data.summary.collections_with_errors}
                {data.summary.collections_with_errors > 0 && (
                  <AlertCircle className="h-5 w-5 text-destructive" />
                )}
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
            <AlertCircle className="h-8 w-8 text-destructive" />
            <p className="text-sm text-destructive">{error}</p>
            <Button variant="outline" size="sm" onClick={load}>
              Reintentar
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Loading skeleton */}
      {loading && !data && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Profesores</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Profesor</TableHead>
                  <TableHead>Documentos</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Chunks</TableHead>
                  <TableHead>Última indexación</TableHead>
                  <TableHead className="text-right">Acciones</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 6 }).map((_, j) => (
                      <TableCell key={j}>
                        <div className="h-4 bg-gray-200 rounded animate-pulse w-3/4" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Professors table */}
      {data && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Profesores ({data.collections.length})</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Profesor</TableHead>
                  <TableHead>Documentos</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Chunks</TableHead>
                  <TableHead>Qdrant Points</TableHead>
                  <TableHead>Última indexación</TableHead>
                  <TableHead className="text-right">Acciones</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.collections.map((col) => (
                  <TableRow key={col.professor_id}>
                    <TableCell className="font-medium">{col.professor_name}</TableCell>
                    <TableCell>{col.total_documents}</TableCell>
                    <TableCell>{statusBadge(col)}</TableCell>
                    <TableCell>{col.total_chunks}</TableCell>
                    <TableCell>{col.qdrant_points}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {col.last_indexed_at
                        ? new Date(col.last_indexed_at).toLocaleString()
                        : '—'}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon" asChild>
                        <Link href={`/admin/documents/${col.professor_id}`}>
                          <Eye className="h-4 w-4" />
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Empty state */}
      {data && data.collections.length === 0 && !loading && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-2">
            <FileText className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">No hay profesores con documentos indexados.</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
