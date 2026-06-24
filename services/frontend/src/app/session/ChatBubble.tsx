'use client'
import { cn } from '@/lib/utils'
import SourceCitation from '@/components/rag/SourceCitation'

export interface Source {
  document_name: string
  relevance_score: number
  snippet: string
  page_number?: string
}

export interface ChatMessage {
  id: string
  role: string
  content: string
  timestamp: string
  sources?: Source[]
}

interface Props {
  message: ChatMessage
}

export default function ChatBubble({ message }: Props) {
  return (
    <div
      className={cn(
        'rounded-lg px-3 py-2 max-w-full',
        message.role === 'student'
          ? 'bg-primary/10 text-right ml-4'
          : 'bg-muted mr-4'
      )}
    >
      <p className="text-xs font-medium text-muted-foreground mb-0.5 capitalize">
        {message.role}
      </p>
      <p>{message.content}</p>
      {message.role === 'assistant' && message.sources && message.sources.length > 0 && (
        <SourceCitation sources={message.sources} compact />
      )}
    </div>
  )
}
