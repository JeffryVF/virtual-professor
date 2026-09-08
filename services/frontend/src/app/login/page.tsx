'use client'

import { useState, useEffect, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { Loader2, BookOpen, LogIn, UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { useAuth } from '@/contexts/AuthContext'
import * as auth from '@/lib/auth'

function LoginForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { login, user, isAuthenticated, isLoading } = useAuth()

  // Login state
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Register state
  const [regName, setRegName] = useState('')
  const [regEmail, setRegEmail] = useState('')
  const [regPassword, setRegPassword] = useState('')
  const [regSubmitting, setRegSubmitting] = useState(false)
  const [regError, setRegError] = useState('')

  const reason = searchParams.get('reason')
  const isNoProfessors = reason === 'no-professors'

  // If there are no professors, redirect students to the student portal,
  // not the admin panel (which requires admin role).
  const redirectTo = isNoProfessors ? '/' : (searchParams.get('redirect') || '/')
  const destinationFor = (role: string) => {
    if (role === 'admin') return '/admin'
    return redirectTo.startsWith('/admin') ? '/' : redirectTo
  }

  // Switch to register tab when redirected because no professors exist
  useEffect(() => {
    if (isNoProfessors) setMode('register')
  }, [isNoProfessors])

  useEffect(() => {
    if (searchParams.get('expired') === 'true') {
      toast.error('Tu sesión ha expirado. Inicia sesión nuevamente.')
    }
  }, [searchParams])

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.push(destinationFor(user?.role ?? ''))
    }
  }, [isLoading, isAuthenticated, router, user, redirectTo])

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const loggedInUser = await login({ email, password })
      router.push(destinationFor(loggedInUser.role))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al iniciar sesión')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault()
    setRegError('')
    setRegSubmitting(true)
    try {
      await auth.register({ name: regName, email: regEmail, password: regPassword })
      // Log in immediately after registering
      const loggedInUser = await login({ email: regEmail, password: regPassword })
      toast.success('Cuenta creada correctamente')
      router.push(destinationFor(loggedInUser.role))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Error al registrarse'
      if (message.toLowerCase().includes('email already registered')) {
        try {
          const loggedInUser = await login({ email: regEmail, password: regPassword })
          toast.success('La cuenta ya existía. Iniciamos sesión correctamente.')
          router.push(destinationFor(loggedInUser.role))
          return
        } catch {
          setEmail(regEmail)
          setPassword('')
          setMode('login')
          setError('Ese correo ya existe. Iniciá sesión con su contraseña.')
          return
        }
      }
      setRegError(message)
    } finally {
      setRegSubmitting(false)
    }
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (isAuthenticated) return null

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="flex justify-center mb-2">
            <BookOpen className="h-8 w-8 text-primary" />
          </div>
          <CardTitle>Virtual Professor</CardTitle>
          <CardDescription>
            {isNoProfessors
              ? 'No hay profesores aún. Inicia sesión o crea una cuenta para agregarlos.'
              : 'Accede a tu cuenta de administrador'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Mode toggle */}
          <div className="flex mb-4 border rounded-lg overflow-hidden">
            <button
              type="button"
              onClick={() => setMode('login')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 text-sm font-medium transition-colors ${
                mode === 'login'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:text-foreground'
              }`}
            >
              <LogIn className="h-3.5 w-3.5" />
              Iniciar sesión
            </button>
            <button
              type="button"
              onClick={() => setMode('register')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 text-sm font-medium transition-colors ${
                mode === 'register'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:text-foreground'
              }`}
            >
              <UserPlus className="h-3.5 w-3.5" />
              Crear cuenta
            </button>
          </div>

          {mode === 'login' ? (
            <>
              {error && (
                <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-600">
                  {error}
                </div>
              )}
              <form onSubmit={handleLogin} className="space-y-4">
                <div className="space-y-2">
                  <Input
                    type="email"
                    placeholder="Correo electrónico"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    required
                    autoFocus={mode === 'login'}
                  />
                </div>
                <div className="space-y-2">
                  <Input
                    type="password"
                    placeholder="Contraseña"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    required
                  />
                </div>
                <Button type="submit" className="w-full" disabled={submitting}>
                  {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  {submitting ? 'Iniciando…' : 'Iniciar sesión'}
                </Button>
              </form>
            </>
          ) : (
            <>
              {regError && (
                <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-600">
                  {regError}
                </div>
              )}
              <form onSubmit={handleRegister} className="space-y-4">
                <div className="space-y-2">
                  <Input
                    placeholder="Nombre completo"
                    value={regName}
                    onChange={e => setRegName(e.target.value)}
                    required
                    autoFocus={mode === 'register'}
                  />
                </div>
                <div className="space-y-2">
                  <Input
                    type="email"
                    placeholder="Correo electrónico"
                    value={regEmail}
                    onChange={e => setRegEmail(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Input
                    type="password"
                    placeholder="Contraseña"
                    value={regPassword}
                    onChange={e => setRegPassword(e.target.value)}
                    required
                    minLength={8}
                  />
                </div>
                <Button type="submit" className="w-full" disabled={regSubmitting}>
                  {regSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  {regSubmitting ? 'Creando…' : 'Crear cuenta'}
                </Button>
              </form>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  )
}
