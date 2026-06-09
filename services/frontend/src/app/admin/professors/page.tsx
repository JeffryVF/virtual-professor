'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { toast } from 'sonner'
import { FileText, Trash2, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import ProfessorForm from '@/components/admin/ProfessorForm'
import { getProfessors, deleteProfessor, type Professor } from '@/lib/api'

const langLabel: Record<string, string> = { es: 'Spanish', en: 'English', both: 'Both' }

export default function ProfessorsPage() {
  const [professors, setProfessors] = useState<Professor[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try { setProfessors(await getProfessors()) }
    catch (err) { toast.error(String(err)) }
    finally { setLoading(false) }
  }

  function handleSaved(saved: Professor) {
    setProfessors(prev => {
      const idx = prev.findIndex(p => p.id === saved.id)
      return idx >= 0 ? prev.with(idx, saved) : [...prev, saved]
    })
  }

  async function handleDelete(prof: Professor) {
    if (!confirm(`Delete "${prof.name}"? This will remove all their documents and knowledge.`)) return
    try {
      await deleteProfessor(prof.id)
      setProfessors(prev => prev.filter(p => p.id !== prof.id))
      toast.success('Professor deleted')
    } catch (err) {
      toast.error(String(err))
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Professors</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage virtual professors and their knowledge</p>
        </div>
        <ProfessorForm onSaved={handleSaved} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">All Professors ({professors.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : professors.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground text-sm">
              No professors yet. Create your first one.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Topic</TableHead>
                  <TableHead>Language</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {professors.map(prof => (
                  <TableRow key={prof.id}>
                    <TableCell className="font-medium">{prof.name}</TableCell>
                    <TableCell>{prof.topic}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{langLabel[prof.language]}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {new Date(prof.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="icon" asChild>
                          <Link href={`/admin/professors/${prof.id}/documents`}>
                            <FileText className="h-4 w-4" />
                          </Link>
                        </Button>
                        <ProfessorForm professor={prof} onSaved={handleSaved} />
                        <Button variant="ghost" size="icon" onClick={() => handleDelete(prof)}>
                          <Trash2 className="h-4 w-4 text-destructive" />
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
