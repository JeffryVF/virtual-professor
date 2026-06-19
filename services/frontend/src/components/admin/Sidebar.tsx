'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { GraduationCap, BookOpen, LayoutDashboard, FileText, Activity, LogOut } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/contexts/AuthContext'

const links = [
  { href: '/admin', label: 'Dashboard', icon: LayoutDashboard, exact: true },
  { href: '/admin/professors', label: 'Professors', icon: GraduationCap, exact: false },
  { href: '/admin/documents', label: 'Documentos', icon: FileText, exact: false },
  { href: '/admin/status', label: 'Estado', icon: Activity, exact: false },
]

export default function Sidebar() {
  const pathname = usePathname()
  const { logout } = useAuth()

  return (
    <aside className="w-60 shrink-0 border-r bg-white flex flex-col">
      <div className="flex items-center gap-2 px-6 py-5 border-b">
        <BookOpen className="h-5 w-5 text-primary" />
        <span className="font-semibold text-sm">Virtual Professor</span>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-1">
        {links.map(({ href, label, icon: Icon, exact }) => {
          const active = exact ? pathname === href : pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                active
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          )
        })}
      </nav>
      <div className="border-t p-3">
        <button
          onClick={logout}
          className="flex w-full items-center gap-3 rounded-md bg-black px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
        >
          <LogOut className="h-4 w-4" />
          Cerrar sesión
        </button>
      </div>
    </aside>
  )
}
