import ProtectedRoute from '@/components/auth/ProtectedRoute'

export default function AdminRoute({ children }: { children: React.ReactNode }) {
  return <ProtectedRoute requiredRole="admin">{children}</ProtectedRoute>
}
