import { getAccessToken, refreshTokens, clearTokens } from '@/lib/auth'
import { handleApiError } from '@/lib/error-handler'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? '/api'

export type Language = 'es' | 'en' | 'both'
export type DocumentStatus = 'pending' | 'processing' | 'ready' | 'error'

export interface Professor {
  id: string
  name: string
  topic: string
  language: Language
  avatar_id: string
  collection: string
  system_prompt: string
  created_at: string
}

export interface ProfessorCreate {
  name: string
  topic: string
  language: Language
  avatar_id: string
  system_prompt: string
}

export interface Document {
  id: string
  professor_id: string
  filename: string
  format: string
  status: DocumentStatus
  chunk_count: number
  error_message: string | null
  uploaded_at: string
}

// ── Auth-aware fetch helpers ───────────────────────────────────────────────────

async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = getAccessToken()
  const headers = new Headers(init?.headers)
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  let res = await fetch(`${API_BASE}${path}`, { ...init, headers })

  if (res.status === 401) {
    const refreshed = await refreshTokens()
    if (refreshed) {
      const retryHeaders = new Headers(init?.headers)
      retryHeaders.set('Authorization', `Bearer ${refreshed.access_token}`)
      res = await fetch(`${API_BASE}${path}`, { ...init, headers: retryHeaders })
    } else {
      clearTokens()
      if (typeof window !== 'undefined') {
        window.location.href = '/login?expired=true'
      }
      throw new Error('Session expired')
    }
  }

  return res
}

async function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authFetch(path, init)
  if (!res.ok) {
    throw await handleApiError(res)
  }
  return res.json() as Promise<T>
}

// ── Professors ────────────────────────────────────────────────────────────────

export const getProfessors = () => authRequest<Professor[]>('/admin/professors')

export const createProfessor = (data: ProfessorCreate) =>
  authRequest<Professor>('/admin/professors', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })

export const updateProfessor = (id: string, data: Partial<ProfessorCreate>) =>
  authRequest<Professor>(`/admin/professors/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })

export const deleteProfessor = async (id: string): Promise<void> => {
  const res = await authFetch(`/admin/professors/${id}`, { method: 'DELETE' })
  if (!res.ok) throw await handleApiError(res)
}

export interface Student {
  id: string
  name: string
  email: string
  language: Language
  created_at: string
}

export interface Session {
  id: string
  student_id: string
  professor_id: string
  started_at: string
  ended_at: string | null
  credits_used: number
}

export interface LiveAvatarConnect {
  livekit_url: string
  livekit_client_token: string
  ws_url: string
  liveavatar_session_id: string
}

// ── Documents ─────────────────────────────────────────────────────────────────

export const getDocuments = (professorId: string) =>
  authRequest<Document[]>(`/admin/professors/${professorId}/documents`)

export const uploadDocument = (professorId: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return authRequest<Document>(`/admin/professors/${professorId}/documents`, {
    method: 'POST',
    body: form,
  })
}

export const deleteDocument = async (documentId: string): Promise<void> => {
  const res = await authFetch(`/admin/documents/${documentId}`, { method: 'DELETE' })
  if (!res.ok) throw await handleApiError(res)
}

// ── RAG / Indexing ────────────────────────────────────────────────────────────

export interface ChunkResponse {
  chunk_index: number
  text: string
  score: number | null
  page_number: string | null
}

export interface CollectionStatus {
  professor_id: string
  professor_name: string
  collection: string
  total_documents: number
  documents_by_status: Record<string, number>
  total_chunks: number
  qdrant_points: number
  last_indexed_at: string | null
  last_error: string | null
}

export interface IndexingStatusResponse {
  collections: CollectionStatus[]
  summary: {
    total_collections: number
    total_documents: number
    total_chunks: number
    collections_with_errors: number
  }
}

export const getIndexingStatus = () =>
  authRequest<IndexingStatusResponse>('/admin/indexing/status')

export const getDocumentChunks = (documentId: string, offset?: number, limit?: number) => {
  const params = new URLSearchParams()
  if (offset !== undefined) params.set('offset', String(offset))
  if (limit !== undefined) params.set('limit', String(limit))
  const qs = params.toString()
  return authRequest<ChunkResponse[]>(`/admin/documents/${documentId}/chunks${qs ? `?${qs}` : ''}`)
}

export const reindexDocument = (documentId: string) =>
  authRequest<{ status: string; document_id: string }>(`/admin/documents/${documentId}/reindex`, {
    method: 'POST',
  })

// ── Students & Sessions ───────────────────────────────────────────────────────

export const createStudent = (name: string, language: Language) => {
  const email = `${name.toLowerCase().replace(/\s+/g, '.')}.${Date.now()}@virtualprofesor.edu`
  return authRequest<Student>('/sessions/students', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, language }),
  })
}

export const createSession = (studentId: string, professorId: string) =>
  authRequest<Session>('/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ student_id: studentId, professor_id: professorId }),
  })

export const connectLiveAvatar = (sessionId: string) =>
  authRequest<LiveAvatarConnect>(`/sessions/${sessionId}/liveavatar-connect`, {
    method: 'POST',
  })

export const getSessionHistory = (sessionId: string) =>
  authRequest<Array<{ id: string; role: string; content: string; timestamp: string }>>(
    `/sessions/${sessionId}/history`
  )

export const endSession = async (sessionId: string): Promise<void> => {
  const res = await authFetch(`/sessions/${sessionId}`, { method: 'DELETE' })
  if (!res.ok) throw await handleApiError(res)
}

export async function speakInSession(sessionId: string, audio: Blob): Promise<ArrayBuffer> {
  const form = new FormData()
  form.append('audio', audio, 'recording')
  const res = await authFetch(`/sessions/${sessionId}/speak`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw await handleApiError(res)
  return res.arrayBuffer()
}
