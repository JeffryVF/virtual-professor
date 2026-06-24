'use client'
import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import {
  ArrowLeft,
  Loader2,
  RefreshCw,
  Trash2,
  Eye,
  AlertCircle,
  FileText,
  SearchX,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from '@/components/ui/dialog'
import {
  getIndexingStatus,
  getDocuments,
  getDocumentChunks,
  deleteDocument,
  reindexDocument,
  type CollectionStatus,
  type Document,
  type ChunkResponse,
} from '@/lib/api'

const statusVariant: Record<string, 'default' | 'secondary' | 'success' | 'destructive' | 'warning'> = {
  pending: 'secondary',
  processing: 'warning',
  ready: 'success',
  error: 'destructive',
}

const statusLabel: Record<string, string> = {
  pending: 'Pendiente',
  processing: 'Procesando',
  ready: 'Listo',
  error: 'Error',
}

export default function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()

  const [collection, setCollection] = useState<CollectionStatus | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [chunks, setChunks] = useState<ChunkResponse[]>([])
  const [chunksLoading, setChunksLoading] = useState(false)
  const [chunksDocId, setChunksDocId] = useState<string | null>(null)
  const [chunksOffset, setChunksOffset] = useState(0)

  const CHUNKS_PAGE_SIZE = 20

  useEffect(() => {
    load()
  }, [id])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [statusRes, docs] = await Promise.all([
        getIndexingStatus(),
        getDocuments(id),
      ])
      const col = statusRes.collections.find((c) => c.professor_id === id) ?? null
      setCollection(col)
      setDocuments(docs)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleLoadChunks(documentId: string) {
    setChunksDocId(documentId)
    setChunksOffset(0)
    setChunksLoading(true)
    try {
      setChunks(await getDocumentChunks(documentId, 0, CHUNKS_PAGE_SIZE))
    } catch (err) {
      toast.error(String(err))
      setChunks([])
    } finally {
      setChunksLoading(false)
    }
  }

  async function handleChunksNext() {
    if (!chunksDocId) return
    const nextOffset = chunksOffset + CHUNKS_PAGE_SIZE
    setChunksLoading(true)
    try {
      const next = await getDocumentChunks(chunksDocId, nextOffset, CHUNKS_PAGE_SIZE)
      setChunks(next)
      setChunksOffset(nextOffset)
    } catch (err) {
      toast.error(String(err))
    } finally {
      setChunksLoading(false)
    }
  }

  async function handleChunksPrev() {
    if (!chunksDocId) return
    const prevOffset = Math.max(0, chunksOffset - CHUNKS_PAGE_SIZE)
    setChunksLoading(true)
    try {
      const prev = await getDocumentChunks(chunksDocId, prevOffset, CHUNKS_PAGE_SIZE)
      setChunks(prev)
      setChunksOffset(prevOffset)
    } catch (err) {
      toast.error(String(err))
    } finally {
      setChunksLoading(false)
    }
  }

  async function handleReindex(documentId: string, filename: string) {
    if (!confirm(`¿Reindexar "${filename}"?`)) return
    try {
      const res = await reindexDocument(documentId)
      toast.success(`Reindexación iniciada: ${res.status}`)
      load()
    } catch (err) {
      toast.error(String(err))
    }
  }

  async function handleDelete(documentId: string, filename: string) {
    if (!confirm(`¿Eliminar "${filename}"? Esta acción no se puede deshacer.`)) return
    try {
      await deleteDocument(documentId)
      setDocuments((prev) => prev.filter((d) => d.id !== documentId))
      toast.success('Documento eliminado')
    } catch (err) {
      toast.error(String(err))
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 bg-gray-200 rounded animate-pulse" />
        <div className="h-4 w-64 bg-gray-200 rounded animate-pulse" />
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Archivo</TableHead>
                  <TableHead>Formato</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Chunks</TableHead>
                  <TableHead>Subido</TableHead>
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
      </div>
    )
  }

  if (error) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 gap-3">
          <AlertCircle className="h-8 w-8 text-destructive" />
          <p className="text-sm text-destructive">{error}</p>
          <Button variant="outline" size="sm" onClick={load}>
            Reintentar
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => router.push('/admin/documents')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-2xl font-semibold">
            {collection?.professor_name ?? 'Profesor'}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {collection?.collection && (
              <span className="font-mono text-xs">{collection.collection}</span>
            )}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} className="ml-auto">
          <RefreshCw className="h-4 w-4 mr-1" />
          Refrescar
        </Button>
      </div>

      {/* Documents table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Documentos ({documents.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {documents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 gap-2">
              <SearchX className="h-8 w-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">No hay documentos para este profesor.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Archivo</TableHead>
                  <TableHead>Formato</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Chunks</TableHead>
                  <TableHead>Subido</TableHead>
                  <TableHead className="text-right">Acciones</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell className="font-medium max-w-[200px] truncate" title={doc.filename}>
                      <FileText className="h-4 w-4 inline mr-1.5 text-muted-foreground" />
                      {doc.filename}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{doc.format}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant[doc.status] ?? 'secondary'}>
                        {statusLabel[doc.status] ?? doc.status}
                      </Badge>
                    </TableCell>
                    <TableCell>{doc.chunk_count}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(doc.uploaded_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {/* Ver chunks dialog */}
                        <Dialog>
                          <DialogTrigger asChild>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleLoadChunks(doc.id)}
                              disabled={doc.chunk_count === 0}
                              title={doc.chunk_count === 0 ? 'No chunks indexed' : 'Ver chunks'}
                            >
                              <Eye className="h-4 w-4 mr-1" />
                              Chunks
                            </Button>
                          </DialogTrigger>
                          <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
                            <DialogHeader>
                              <DialogTitle className="flex items-center gap-2">
                                <FileText className="h-4 w-4" />
                                Chunks — {doc.filename}
                              </DialogTitle>
                            </DialogHeader>
                            {chunksLoading ? (
                              <div className="flex justify-center py-8">
                                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                              </div>
                            ) : chunks.length === 0 ? (
                              <div className="text-center py-8 text-sm text-muted-foreground">
                                No chunks indexed
                              </div>
                            ) : (
                              <div className="space-y-3">
                                {chunks.map((chunk) => (
                                  <div
                                    key={chunk.chunk_index}
                                    className="rounded-lg border p-3 text-sm space-y-1"
                                  >
                                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                                      <span className="font-medium">
                                        Chunk #{chunk.chunk_index}
                                      </span>
                                      {chunk.page_number && <span>Pág. {chunk.page_number}</span>}
                                    </div>
                                    <p className="text-gray-700 line-clamp-3">
                                      {chunk.text.length > 200
                                        ? chunk.text.slice(0, 200) + '…'
                                        : chunk.text}
                                    </p>
                                    {chunk.score !== null && (
                                      <p className="text-xs text-muted-foreground">
                                        Score: {chunk.score.toFixed(3)}
                                      </p>
                                    )}
                                  </div>
                                ))}
                                {/* Pagination */}
                                <div className="flex items-center justify-between pt-2">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={chunksOffset === 0}
                                    onClick={handleChunksPrev}
                                  >
                                    Anteriores
                                  </Button>
                                  <span className="text-xs text-muted-foreground">
                                    Offset {chunksOffset}
                                  </span>
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={chunks.length < CHUNKS_PAGE_SIZE}
                                    onClick={handleChunksNext}
                                  >
                                    Siguientes
                                  </Button>
                                </div>
                              </div>
                            )}
                          </DialogContent>
                        </Dialog>

                        {/* Reindex */}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleReindex(doc.id, doc.filename)}
                        >
                          <RefreshCw className="h-4 w-4 mr-1" />
                          Reindex
                        </Button>

                        {/* Delete */}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(doc.id, doc.filename)}
                        >
                          <Trash2 className="h-4 w-4 text-destructive mr-1" />
                          Delete
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
