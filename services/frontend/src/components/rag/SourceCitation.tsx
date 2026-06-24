'use client'
import { useState } from 'react'
import { cn } from '@/lib/utils'

interface Source {
  document_name: string
  relevance_score: number
  snippet: string
  page_number?: string
}

interface Props {
  sources: Source[]
  compact?: boolean
}

function relevanceColor(score: number): string {
  if (score > 0.95) return 'bg-green-100 text-green-800 border-green-200'
  if (score > 0.75) return 'bg-yellow-100 text-yellow-800 border-yellow-200'
  return 'bg-gray-100 text-gray-500 border-gray-200'
}

function formatDocName(name: string): string {
  if (!name || name.startsWith('Deleted:')) return ''
  return name.length > 60 ? name.slice(0, 60) + '…' : name
}

export default function SourceCitation({ sources, compact }: Props) {
  const [expanded, setExpanded] = useState(false)

  if (!sources || sources.length === 0) {
    return <p className="mt-1 text-xs text-gray-400">Sin fuentes específicas</p>
  }

  if (compact) {
    return (
      <div className="mt-1">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          📄 {sources.length} {sources.length === 1 ? 'fuente' : 'fuentes'}
        </button>
        {expanded && <SourcesList sources={sources} />}
      </div>
    )
  }

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="text-xs text-primary hover:underline transition-colors"
      >
        {expanded ? 'Ocultar fuentes' : `Ver fuentes (${sources.length})`}
      </button>
      <div
        className={cn(
          'grid gap-2 overflow-hidden transition-all duration-300 ease-in-out',
          expanded ? 'mt-2 grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
        )}
      >
        <div className="min-h-0">
          <SourcesList sources={sources} />
        </div>
      </div>
    </div>
  )
}

function SourcesList({ sources }: { sources: Source[] }) {
  return (
    <div className="space-y-2">
      {sources.map((src, i) => {
        const isDeleted = !src.document_name || src.document_name.startsWith('Deleted:')
        const displayName = formatDocName(src.document_name)

        return (
          <div
            key={i}
            className={cn(
              'rounded-lg border p-3 text-xs space-y-1',
              isDeleted ? 'bg-gray-50 border-gray-200' : 'bg-white'
            )}
          >
            <div className="flex items-center justify-between gap-2">
              {isDeleted ? (
                <span className="text-gray-400 italic">(Fuente eliminada)</span>
              ) : (
                <span
                  className="font-medium truncate"
                  title={src.document_name}
                >
                  {displayName}
                </span>
              )}
              {!isDeleted && (
                <span
                  className={cn(
                    'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold border',
                    relevanceColor(src.relevance_score)
                  )}
                >
                  {(src.relevance_score * 100).toFixed(0)}%
                </span>
              )}
            </div>
            {!isDeleted && src.snippet && (
              <p className="text-gray-600 line-clamp-2">{src.snippet}</p>
            )}
            {!isDeleted && src.page_number && (
              <p className="text-gray-400">Pág. {src.page_number}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}
