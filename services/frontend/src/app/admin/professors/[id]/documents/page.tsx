'use client'
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { toast } from 'sonner'
import { ArrowLeft, Trash2, UploadCloud, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { getDocuments, uploadDocument, deleteDocument, type Document } from '@/lib/api'
import type { ApiError } from '@/lib/error-handler'

const statusVariant: Record<string, BadgeProps['variant']> = {
  ready: 'success',
  processing: 'warning',
  pending: 'secondary',
  error: 'destructive',
}

export default function DocumentsPage() {
  const { id } = useParams<{ id: string }>()
  const [docs, setDocs] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [limitError, setLimitError] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { load() }, [id])

  async function load() {
    setLoading(true)
    try { setDocs(await getDocuments(id)) }
    catch (err) { toast.error(String(err)) }
    finally { setLoading(false) }
  }

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const doc = await uploadDocument(id, file)
        setDocs(prev => [doc, ...prev])
        toast.success(`"${file.name}" queued for processing`)
      }
    } catch (err) {
      const apiError = err as Partial<ApiError>
      if (apiError.status === 413 || apiError.code === 'FILE_TOO_LARGE') {
        setLimitError(true)
      } else {
        toast.error(apiError.detail ?? apiError.message ?? String(err))
      }
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function handleDelete(doc: Document) {
    if (!confirm(`Remove "${doc.filename}"?`)) return
    try {
      await deleteDocument(doc.id)
      setDocs(prev => prev.filter(d => d.id !== doc.id))
      toast.success('Document removed')
    } catch (err) {
      toast.error(String(err))
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    handleFiles(e.dataTransfer.files)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" asChild>
          <Link href="/admin/professors"><ArrowLeft className="h-4 w-4" /></Link>
        </Button>
        <div>
          <h1 className="text-2xl font-semibold">Documents</h1>
          <p className="text-sm text-muted-foreground mt-1">Upload knowledge for this professor</p>
        </div>
        <Button variant="outline" size="sm" className="ml-auto" onClick={load}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />Refresh
        </Button>
      </div>

      {/* Drop zone */}
      <div
        onDrop={onDrop}
        onDragOver={e => e.preventDefault()}
        onClick={() => inputRef.current?.click()}
        className="border-2 border-dashed rounded-lg p-10 text-center cursor-pointer hover:border-primary hover:bg-accent/30 transition-colors"
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          accept=".pdf,.docx,.pptx,.txt,.url"
          onChange={e => handleFiles(e.target.files)}
        />
        {uploading ? (
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Loader2 className="h-8 w-8 animate-spin" />
            <p className="text-sm">Uploading…</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <UploadCloud className="h-8 w-8" />
            <p className="text-sm font-medium">Drop files here or click to upload</p>
            <p className="text-xs">PDF, DOCX, PPTX, TXT, MP3, MP4, WAV, CSV, JSON</p>
          </div>
        )}
      </div>

      {/* Documents table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Knowledge Documents ({docs.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : docs.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground text-sm">No documents uploaded yet.</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>File</TableHead>
                  <TableHead>Format</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Chunks</TableHead>
                  <TableHead>Uploaded</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {docs.map(doc => (
                  <TableRow key={doc.id}>
                    <TableCell className="font-medium max-w-xs truncate">{doc.filename}</TableCell>
                    <TableCell className="uppercase text-xs text-muted-foreground">{doc.format}</TableCell>
                    <TableCell>
                      <Badge variant={statusVariant[doc.status] ?? 'secondary'}>{doc.status}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{doc.chunk_count || '—'}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(doc.uploaded_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon" onClick={() => handleDelete(doc)}>
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={limitError} onOpenChange={setLimitError}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Archivo demasiado grande</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            El archivo supera el límite permitido de 50 MB. Reduce su tamaño o divide el documento en varios archivos e inténtalo de nuevo.
          </p>
          <Button onClick={() => setLimitError(false)} className="mt-2">Entendido</Button>
        </DialogContent>
      </Dialog>
    </div>
  )
}
