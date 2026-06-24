import Sidebar from '@/components/admin/Sidebar'
import AdminRoute from '@/components/auth/AdminRoute'
import ErrorBoundary from '@/components/ErrorBoundary'

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminRoute>
      <ErrorBoundary>
        <div className="flex h-screen bg-gray-50">
          <Sidebar />
          <main className="flex-1 overflow-auto p-8">{children}</main>
        </div>
      </ErrorBoundary>
    </AdminRoute>
  )
}
