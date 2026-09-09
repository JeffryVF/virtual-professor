import type { Env } from '../types'
import { parseItemKey, search } from '../cloudflare'
import { isConfigured } from '../cloudflare'
import { num } from '../utils'

export interface ScoredChunk {
  text: string
  score: number | null
  sourceFilename: string
  documentId: string
  pageLabel: string | null
}

export interface ContextChunk {
  text: string
  source_document: string
  source_document_id: string
  source_page?: string | null
  trace_id?: string | null
  score?: number | null
}

export function filterChunksByScore(chunks: ScoredChunk[], minScore: number): ScoredChunk[] {
  return chunks.filter((c) => c.score !== null && c.score !== undefined && c.score >= minScore)
}

export function chunkText(raw: Record<string, unknown>): string {
  const content = raw.text ?? raw.content
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    const parts: string[] = []
    for (const item of content) {
      if (typeof item === 'object' && item !== null && (item as Record<string, unknown>).text) {
        parts.push(String((item as Record<string, unknown>).text))
      } else if (typeof item === 'string') {
        parts.push(item)
      }
    }
    return parts.join('\n')
  }
  return ''
}

export function parseSearchChunk(raw: Record<string, unknown>): ScoredChunk {
  const item = (raw.item && typeof raw.item === 'object' ? raw.item : {}) as Record<string, unknown>
  const key = String(item.key ?? raw.filename ?? '')
  const { documentId, filename } = parseItemKey(key)
  const metadata = (item.metadata && typeof item.metadata === 'object' ? item.metadata : {}) as Record<string, unknown>
  const source = String(metadata.filename ?? filename ?? documentId ?? key)
  let score: number | null = typeof raw.score === 'number' ? raw.score : null
  if (score === null) {
    const details = (raw.scoring_details && typeof raw.scoring_details === 'object'
      ? raw.scoring_details
      : {}) as Record<string, unknown>
    score =
      typeof details.reranking_score === 'number'
        ? details.reranking_score
        : typeof details.vector_score === 'number'
          ? details.vector_score
          : null
  }
  const page = metadata.page_label ?? raw.page
  return {
    text: chunkText(raw),
    score,
    sourceFilename: source,
    documentId: documentId || String(metadata.document_id ?? ''),
    pageLabel: typeof page === 'string' ? page : page != null ? String(page) : null,
  }
}

export async function retrieveContext(
  env: Env,
  query: string,
  professorCollection: string,
  options: { topK?: number; minScore?: number; timeoutMs?: number } = {},
): Promise<ContextChunk[]> {
  if (!isConfigured(env)) return []
  const floor = options.minScore !== undefined ? options.minScore : num(env, 'RAG_MIN_RELEVANCE_SCORE', 0.4)
  let rawChunks: Record<string, unknown>[]
  try {
    rawChunks = await search(env, query, {
      folderPrefix: professorCollection,
      maxNumResults: options.topK,
      timeoutMs: options.timeoutMs,
    })
  } catch {
    return []
  }
  const chunks = rawChunks.filter((c) => typeof c === 'object' && c !== null).map(parseSearchChunk)
  const filtered = filterChunksByScore(chunks, floor)
  return filtered
    .filter((c) => c.text.trim().length > 0)
    .map((c) => ({
      text: c.text,
      source_document: c.sourceFilename || c.documentId,
      source_document_id: c.documentId,
      source_page: c.pageLabel,
      score: c.score,
    }))
}

export async function listDocumentChunks(
  env: Env,
  professorCollection: string,
  documentId: string,
  filename: string,
  options: { offset?: number; limit?: number } = {},
): Promise<ScoredChunk[]> {
  if (!isConfigured(env)) return []
  const offset = options.offset ?? 0
  const limit = options.limit ?? 50
  try {
    const rawChunks = await search(env, filename || 'document', {
      folderPrefix: `${professorCollection}/${documentId}`,
      maxNumResults: Math.min(offset + limit, 50),
    })
    const all = rawChunks.map(parseSearchChunk)
    return all.slice(offset, offset + limit)
  } catch {
    return []
  }
}