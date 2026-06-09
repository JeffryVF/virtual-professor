'use client'
import dynamic from 'next/dynamic'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, BookOpen } from 'lucide-react'
import { Button } from '@/components/ui/button'

// AvatarSession uses browser APIs (WebRTC, MediaRecorder) — disable SSR
const AvatarSession = dynamic(
  () => import('@/components/student/AvatarSession'),
  { ssr: false, loading: () => <div className="flex-1 bg-black rounded-xl animate-pulse" /> }
)

export default function SessionPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()

  function handleEnded() {
    router.push('/')
  }

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b px-6 py-3 flex items-center gap-3 shrink-0">
        <Button variant="ghost" size="icon" onClick={() => router.push('/')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <BookOpen className="h-4 w-4 text-primary" />
        <span className="font-medium text-sm">Virtual Professor — Live Session</span>
      </header>

      {/* Session content */}
      <div className="flex-1 p-6 min-h-0">
        <AvatarSession sessionId={id} onEnded={handleEnded} />
      </div>
    </div>
  )
}
