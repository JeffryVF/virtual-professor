import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { GraduationCap } from 'lucide-react'
import type { Professor } from '@/lib/api'

const langLabel: Record<string, string> = { es: 'Español', en: 'English', both: 'ES / EN' }

interface Props {
  professor: Professor
  onClick: () => void
}

export default function ProfessorCard({ professor, onClick }: Props) {
  return (
    <Card
      onClick={onClick}
      className="cursor-pointer hover:shadow-md hover:border-primary/40 transition-all group"
    >
      {/* Avatar placeholder */}
      <div className="h-40 bg-gradient-to-br from-primary/10 to-primary/5 flex items-center justify-center rounded-t-xl">
        <GraduationCap className="h-16 w-16 text-primary/40 group-hover:text-primary/60 transition-colors" />
      </div>
      <CardContent className="pt-4 pb-5 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-semibold leading-tight">{professor.name}</h3>
          <Badge variant="secondary" className="shrink-0 text-xs">{langLabel[professor.language]}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">{professor.topic}</p>
      </CardContent>
    </Card>
  )
}
