'use client'

import { useEffect } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { Loader2 } from 'lucide-react'

interface ProtectedRouteProps {
  children: React.ReactNode
  requiredRole?: 'admin' | 'student'
}

export default function ProtectedRoute({ children, requiredRole }: ProtectedRouteProps) {
  const { user, isLoading, isAuthenticated } = useAuth()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (isLoading) return
    if (!isAuthenticated) {
      router.push(`/login?redirect=${encodeURIComponent(pathname)}`)
    }
  }, [isLoading, isAuthenticated, router, pathname])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!isAuthenticated) return null

  if (requiredRole && user?.role !== requiredRole) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4">
        <h1 className="text-6xl font-bold text-muted-foreground">403</h1>
        <p className="text-lg text-muted-foreground">No tienes permiso para acceder a esta página.</p>
      </div>
    )
  }

  return <>{children}</>
}
