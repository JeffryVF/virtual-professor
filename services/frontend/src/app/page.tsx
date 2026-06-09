'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Loader2, BookOpen } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import ProfessorCard from '@/components/student/ProfessorCard'
import { getProfessors, createStudent, createSession, type Professor, type Language } from '@/lib/api'

const STUDENT_KEY = 'vp_student_id'

export default function StudentPortal() {
  const router = useRouter()
  const [professors, setProfessors] = useState<Professor[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Professor | null>(null)
  const [name, setName] = useState('')
  const [language, setLanguage] = useState<Language>('es')
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    getProfessors()
      .then(setProfessors)
      .catch(err => toast.error(String(err)))
      .finally(() => setLoading(false))
  }, [])

  async function handleStart() {
    if (!selected || !name.trim()) return
    setStarting(true)
    try {
      let studentId = localStorage.getItem(STUDENT_KEY)
      if (!studentId) {
        const student = await createStudent(name.trim(), language)
        studentId = student.id
        localStorage.setItem(STUDENT_KEY, studentId)
      }
      const session = await createSession(studentId, selected.id)
      router.push(`/session/${session.id}?professor=${selected.id}`)
    } catch (err) {
      toast.error(String(err))
      setStarting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b px-6 py-4 flex items-center gap-2">
        <BookOpen className="h-5 w-5 text-primary" />
        <span className="font-semibold">Virtual Professor</span>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">
        <div className="mb-8">
          <h1 className="text-3xl font-bold">Choose your professor</h1>
          <p className="text-muted-foreground mt-1">Select a professor to start a voice session</p>
        </div>

        {loading ? (
          <div className="flex justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : professors.length === 0 ? (
          <p className="text-center text-muted-foreground py-20">
            No professors available yet. Check back soon.
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {professors.map(prof => (
              <ProfessorCard key={prof.id} professor={prof} onClick={() => setSelected(prof)} />
            ))}
          </div>
        )}
      </main>

      {/* Start session dialog */}
      <Dialog open={!!selected} onOpenChange={open => !open && setSelected(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Start session with {selected?.name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-2">
            <div className="space-y-1.5">
              <Label>Your name</Label>
              <Input
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="Ana López"
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label>Language</Label>
              <Select value={language} onValueChange={v => setLanguage(v as Language)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="es">Spanish</SelectItem>
                  <SelectItem value="en">English</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button className="w-full" onClick={handleStart} disabled={!name.trim() || starting}>
              {starting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              {starting ? 'Starting…' : 'Start session'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
