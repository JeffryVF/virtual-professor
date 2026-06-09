const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? '/api'
const ADMIN_KEY = process.env.NEXT_PUBLIC_ADMIN_KEY ?? 'changeme'

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'X-Admin-Key': ADMIN_KEY,
      ...init?.headers,
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${text}`)
  }
  return res.json() as Promise<T>
}

// ── Professors ────────────────────────────────────────────────────────────────

export const getProfessors = () =>
  request<Professor[]>('/admin/professors')

export const createProfessor = (data: ProfessorCreate) =>
  request<Professor>('/admin/professors', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })

export const updateProfessor = (id: string, data: Partial<ProfessorCreate>) =>
  request<Professor>(`/admin/professors/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })

export const deleteProfessor = (id: string) =>
  fetch(`${API_BASE}/admin/professors/${id}`, {
    method: 'DELETE',
    headers: { 'X-Admin-Key': ADMIN_KEY },
  })

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
  request<Document[]>(`/admin/professors/${professorId}/documents`)

export const uploadDocument = (professorId: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return request<Document>(`/admin/professors/${professorId}/documents`, {
    method: 'POST',
    body: form,
  })
}

export const deleteDocument = (documentId: string) =>
  fetch(`${API_BASE}/admin/documents/${documentId}`, {
    method: 'DELETE',
    headers: { 'X-Admin-Key': ADMIN_KEY },
  })

// ── Students & Sessions ───────────────────────────────────────────────────────

export const createStudent = (name: string, language: Language) => {
  const email = `${name.toLowerCase().replace(/\s+/g, '.')}.${Date.now()}@virtualprofesor.edu`
  return request<Student>('/sessions/students', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, language }),
  })
}

export const createSession = (studentId: string, professorId: string) =>
  request<Session>('/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ student_id: studentId, professor_id: professorId }),
  })

export const connectLiveAvatar = (sessionId: string) =>
  request<LiveAvatarConnect>(`/sessions/${sessionId}/liveavatar-connect`, {
    method: 'POST',
  })

export const getSessionHistory = (sessionId: string) =>
  request<Array<{ id: string; role: string; content: string; timestamp: string }>>(
    `/sessions/${sessionId}/history`
  )

export const endSession = (sessionId: string) =>
  fetch(`${API_BASE}/sessions/${sessionId}`, { method: 'DELETE' })

export async function speakInSession(sessionId: string, audio: Blob): Promise<ArrayBuffer> {
  const form = new FormData()
  form.append('audio', audio, 'recording.webm')
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/speak`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.arrayBuffer()
}
