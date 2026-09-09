import { SELF } from 'cloudflare:test'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, json, adminHeaders, migrate } from './helpers'

vi.mock('../src/services/tts', () => ({
  synthesize: vi.fn(async () => ({ audio: new Uint8Array([0x49, 0x44, 0x33, 0x04]), ok: true })),
}))

const zaiAnswer = 'La inteligencia artificial es el campo que estudia sistemas capaces de simular la inteligencia humana.'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function searchChunk(collection: string): Record<string, unknown> {
  return {
    item: { key: `${collection}/doc-1/doc.pdf`, metadata: { filename: 'doc.pdf', document_id: 'doc-1' } },
    score: 0.95,
    text: zaiAnswer,
  }
}

function stubGlobalFetch(collection: string): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string | URL) => {
      const u = new URL(String(url))
      const path = u.pathname
      if (path.endsWith('/search')) {
        return jsonResponse({ success: true, result: { chunks: [searchChunk(collection)] } })
      }
      if (path.endsWith('/items')) {
        return jsonResponse({ success: true, result: { items: [] } })
      }
      if (u.hostname.endsWith('z.ai')) {
        return jsonResponse({ choices: [{ message: { content: zaiAnswer } }] })
      }
      return jsonResponse({ success: true, result: { id: 'test-instance' } })
    }),
  )
}

async function createProfessor(): Promise<{ id: string; collection: string }> {
  const res = await SELF.fetch(api('/admin/professors'), {
    method: 'POST',
    headers: { ...json, ...adminHeaders() },
    body: JSON.stringify({
      name: 'Prof. IA',
      topic: 'Inteligencia Artificial',
      language: 'es',
      system_prompt: 'Responde sobre inteligencia artificial.',
    }),
  })
  expect(res.status).toBe(201)
  return (await res.json()) as { id: string; collection: string; name: string }
}

async function createStudent(): Promise<{ id: string }> {
  const res = await SELF.fetch(api('/sessions/students'), {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ name: 'Bob', email: 'bob@test.com', language: 'es' }),
  })
  expect(res.status).toBe(201)
  return (await res.json()) as { id: string }
}

async function createSession(studentId: string, professorId: string): Promise<{ id: string }> {
  const res = await SELF.fetch(api('/sessions'), {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ student_id: studentId, professor_id: professorId }),
  })
  expect(res.status).toBe(201)
  return (await res.json()) as { id: string }
}

interface Message {
  id: string
  session_id: string
  role: 'student' | 'professor'
  content: string
  audio_path: string | null
  sources_json: string | null
  timestamp: string
}

describe('sessions', () => {
  beforeAll(async () => {
    await migrate()
  })

  beforeEach(() => {
    stubGlobalFetch('prof-calc')
  })

  it('creates students and dedupes by email', async () => {
    const first = await createStudent()
    const second = await createStudent()
    expect(second.id).toBe(first.id)
  })

  it('creates a session and rejects a missing professor', async () => {
    const prof = await createProfessor()
    const student = await createStudent()
    const session = await createSession(student.id, prof.id)
    expect(session.id).toBeTruthy()

    const missing = await SELF.fetch(api('/sessions'), {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ student_id: student.id, professor_id: 'does-not-exist' }),
    })
    expect(missing.status).toBe(404)
  })

  it('answers an in-scope question with MP3 audio', async () => {
    const prof = await createProfessor()
    stubGlobalFetch(prof.collection)
    const student = await createStudent()
    const session = await createSession(student.id, prof.id)

    const res = await SELF.fetch(api(`/sessions/${session.id}/speak`), {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ text: '¿Qué es la inteligencia artificial?' }),
    })
    expect(res.status).toBe(200)
    expect(res.headers.get('Content-Type')).toBe('audio/mpeg')
    const audioBytes = new Uint8Array(await res.arrayBuffer())
    expect(audioBytes.byteLength).toBe(4)
    expect(audioBytes[0]).toBe(0x49) // 'I'

    const history = await SELF.fetch(api(`/sessions/${session.id}/history`))
    expect(history.status).toBe(200)
    const messages = (await history.json()) as Message[]
    expect(messages.some((m) => m.role === 'student' && m.content.includes('inteligencia'))).toBe(true)
    const assistant = messages.find((m) => m.role === 'professor')
    expect(assistant).toBeTruthy()
    expect(assistant!.content).toContain('inteligencia')
    expect(assistant!.sources_json).toBeTruthy()
  })

  it('answers an out-of-scope question with MP3 of the topic reminder', async () => {
    const prof = await createProfessor()
    const student = await createStudent()
    const session = await createSession(student.id, prof.id)

    const res = await SELF.fetch(api(`/sessions/${session.id}/speak`), {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ text: 'Cuéntame un chiste' }),
    })
    expect(res.status).toBe(200)
    expect(res.headers.get('Content-Type')).toBe('audio/mpeg')

    const history = await SELF.fetch(api(`/sessions/${session.id}/history`))
    const messages = (await history.json()) as Message[]
    const assistant = messages.find((m) => m.role === 'professor')
    expect(assistant).toBeTruthy()
    expect(assistant!.content).toContain('Inteligencia Artificial')
  })

  it('handles an empty transcript', async () => {
    const prof = await createProfessor()
    const student = await createStudent()
    const session = await createSession(student.id, prof.id)

    const res = await SELF.fetch(api(`/sessions/${session.id}/speak`), {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ text: '' }),
    })
    expect(res.status).toBe(200)
    const body = (await res.json()) as { text: string; audio: unknown }
    expect(body.audio).toBeNull()
  })

  it('rejects a speak call for an unknown session', async () => {
    const res = await SELF.fetch(api('/sessions/no-such-session/speak'), {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ text: '¿Qué es la inteligencia artificial?' }),
    })
    expect(res.status).toBe(404)
  })

  it('ends a session and blocks further speaks', async () => {
    const prof = await createProfessor()
    const student = await createStudent()
    const session = await createSession(student.id, prof.id)

    const del = await SELF.fetch(api(`/sessions/${session.id}`), { method: 'DELETE' })
    expect(del.status).toBe(204)

    const speak = await SELF.fetch(api(`/sessions/${session.id}/speak`), {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ text: '¿Qué es la inteligencia artificial?' }),
    })
    expect(speak.status).toBe(404)
  })
})