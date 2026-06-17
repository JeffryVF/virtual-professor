import Sidebar from '@/components/admin/Sidebar'
import AdminRoute from '@/components/auth/AdminRoute'

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminRoute>
      <div className="flex h-screen bg-gray-50">
        <Sidebar />
        <main className="flex-1 overflow-auto p-8">{children}</main>
      </div>
    </AdminRoute>
  )
}
