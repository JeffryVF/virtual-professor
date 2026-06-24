'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Loader2, BookOpen, LogOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import ProfessorCard from '@/components/student/ProfessorCard'
import { getPublicProfessors, createStudent, createSession, type Professor, type Language } from '@/lib/api'
import { useAuth } from '@/contexts/AuthContext'

const STUDENT_KEY = 'vp_student_id'

export default function StudentPortal() {
  const router = useRouter()
  const { logout: authLogout, isAuthenticated } = useAuth()
  const [professors, setProfessors] = useState<Professor[]>([])
  const [loading, setLoading] = useState(true)
  const [noProfessors, setNoProfessors] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Professor | null>(null)
  const [name, setName] = useState('')
  const [language, setLanguage] = useState<Language>('es')
  const [starting, setStarting] = useState(false)
  const [hasStudentId, setHasStudentId] = useState(false)

  useEffect(() => {
    setHasStudentId(!!localStorage.getItem(STUDENT_KEY))
  }, [])

  useEffect(() => {
    getPublicProfessors()
      .then(list => {
        if (list.length === 0) {
          setNoProfessors(true)
          return
        }
        setProfessors(list)
        setNoProfessors(false)
      })
      .catch(err => {
        console.error('Failed to load professors:', err)
        setLoadError('No pudimos cargar los profesores. Intenta de nuevo en unos segundos.')
        setNoProfessors(true)
      })
      .finally(() => setLoading(false))
  }, [router])

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

  function handleLogout() {
    localStorage.removeItem(STUDENT_KEY)
    if (isAuthenticated) authLogout()
    setHasStudentId(false)
    toast.success('Sesión cerrada')
  }

  const showLogout = hasStudentId || isAuthenticated

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b px-6 py-4 flex items-center gap-2">
        <BookOpen className="h-5 w-5 text-primary" />
        <span className="font-semibold">Virtual Professor</span>
        {showLogout && (
          <button
            onClick={handleLogout}
            className="ml-auto flex items-center gap-2 rounded-md bg-black px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-gray-800"
          >
            <LogOut className="h-3.5 w-3.5" />
            Cerrar sesión
          </button>
        )}
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
        ) : noProfessors ? (
          <div className="max-w-xl mx-auto rounded-lg border bg-white p-8 text-center shadow-sm">
            <h2 className="text-2xl font-semibold">No hay profesores todavía</h2>
            <p className="mt-2 text-muted-foreground">
              {loadError ?? 'Cuando se cree el primer profesor, aparecerá aquí para que los estudiantes empiecen una sesión.'}
            </p>
            <div className="mt-6 flex items-center justify-center gap-3">
              <Button onClick={() => router.push('/login?reason=no-professors')}>
                Ir a iniciar sesión
              </Button>
            </div>
          </div>
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
