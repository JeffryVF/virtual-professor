import { Hono } from 'hono'

import type { Context } from '../context'
import type { MessageRow, ProfessorRow, SessionRow, StudentRow } from '../types'
import { int, nowIso, uuid } from '../utils'
import {
  generateResponse,
  historyToMessages,
  isInScope,
  resolveLanguage,
  truncateForTts,
} from '../services/llm'
import { retrieveContext } from '../services/rag'
import type { ContextChunk } from '../services/rag'
import { synthesize } from '../services/tts'

const app = new Hono<Context>()

function studentResponse(s: StudentRow) {
  return { id: s.id, name: s.name, email: s.email, language: s.language, created_at: s.created_at }
}

function sessionResponse(s: SessionRow) {
  return {
    id: s.id,
    student_id: s.student_id,
    professor_id: s.professor_id,
    started_at: s.started_at,
    ended_at: s.ended_at,
    credits_used: s.credits_used,
  }
}

function messageResponse(m: MessageRow) {
  return {
    id: m.id,
    session_id: m.session_id,
    role: m.role,
    content: m.content,
    audio_path: m.audio_path,
    sources_json: m.sources_json,
    timestamp: m.timestamp,
  }
}

async function getSessionOrNull(db: D1Database, id: string): Promise<SessionRow | null> {
  return (await db.prepare('SELECT * FROM sessions WHERE id = ?1').bind(id).first<SessionRow>()) ?? null
}

async function getProfessor(db: D1Database, id: string): Promise<ProfessorRow | null> {
  return (await db.prepare('SELECT * FROM professors WHERE id = ?1').bind(id).first<ProfessorRow>()) ?? null
}

async function getHistory(db: D1Database, sessionId: string): Promise<MessageRow[]> {
  const { results } = await db
    .prepare('SELECT * FROM messages WHERE session_id = ?1 ORDER BY timestamp ASC')
    .bind(sessionId)
    .all<MessageRow>()
  return results
}

function truncateForTtsText(totalText: string, maxChars: number): string {
  return truncateForTts(totalText, maxChars)
}

app.post('/students', async (c) => {
  const body = await c.req.json().catch(() => null)
  const name = typeof body?.name === 'string' ? body.name.trim() : ''
  const email = typeof body?.email === 'string' ? body.email.trim().toLowerCase() : ''
  const language = typeof body?.language === 'string' ? body.language : 'en'

  const existing = await c.env.DB.prepare('SELECT * FROM students WHERE email = ?1').bind(email).first<StudentRow>()
  if (existing) return c.json(studentResponse(existing), 201)

  const student: StudentRow = { id: uuid(), name, email, language, created_at: nowIso() }
  const inserted = await c.env.DB.prepare(
    `INSERT INTO students (id, name, email, language, created_at) VALUES (?1, ?2, ?3, ?4, ?5)`,
  )
    .bind(student.id, student.name, student.email, student.language, student.created_at)
    .run()
  if (!inserted.success) {
    const raced = await c.env.DB.prepare('SELECT * FROM students WHERE email = ?1').bind(email).first<StudentRow>()
    if (raced) return c.json(studentResponse(raced), 201)
  }
  return c.json(studentResponse(student), 201)
})

app.post('', async (c) => {
  const body = await c.req.json().catch(() => null)
  const studentId = typeof body?.student_id === 'string' ? body.student_id : ''
  const professorId = typeof body?.professor_id === 'string' ? body.professor_id : ''

  if (!(await getProfessor(c.env.DB, professorId))) return c.json({ detail: 'Professor not found' }, 404)
  const student = await c.env.DB.prepare('SELECT id FROM students WHERE id = ?1').bind(studentId).first()
  if (!student) return c.json({ detail: 'Student not found' }, 404)

  const session: SessionRow = {
    id: uuid(),
    student_id: studentId,
    professor_id: professorId,
    started_at: nowIso(),
    ended_at: null,
    credits_used: 0.0,
  }
  await c.env.DB.prepare(
    `INSERT INTO sessions (id, student_id, professor_id, started_at, ended_at, credits_used)
     VALUES (?1, ?2, ?3, ?4, NULL, 0.0)`,
  )
    .bind(session.id, session.student_id, session.professor_id, session.started_at)
    .run()
  return c.json(sessionResponse(session), 201)
})

app.post('/:sessionId/speak', async (c) => {
  const sessionId = c.req.param('sessionId')
  const body = await c.req.json().catch(() => null)
  const transcript = (typeof body?.text === 'string' ? body.text : '').trim()

  const session = await getSessionOrNull(c.env.DB, sessionId)
  if (!session || session.ended_at) {
    return c.json({ detail: 'Session not found or already ended' }, 404)
  }
  const professor = await getProfessor(c.env.DB, session.professor_id)
  if (!professor) return c.json({ detail: 'Professor not found' }, 404)

  const responseLang = resolveLanguage(professor.language, transcript)
  let contextChunks: ContextChunk[] = []
  let lowRelevance = false
  let responseText = ''

  if (!transcript) {
    responseText =
      responseLang === 'es'
        ? `No pude entender tu audio. Intenta nuevamente sobre ${professor.topic}.`
        : `I couldn't understand the audio. Please try again about ${professor.topic}.`
  } else {
    let inScope = true
    try {
      inScope = await isInScope(c.env, professor.topic, transcript)
    } catch {
      inScope = true
    }

    if (!inScope) {
      responseText =
        responseLang === 'es'
          ? `Por favor realiza preguntas relacionadas con ${professor.topic}. Solo puedo ayudarte con ese tema.`
          : `Please ask questions related to ${professor.topic}. I can only help with that subject.`
    } else {
      let ragFailed = false
      try {
        contextChunks = await retrieveContext(c.env, transcript, professor.collection)
      } catch {
        ragFailed = true
        contextChunks = [
          {
            text: 'Note: knowledge base unavailable',
            source_document: '',
            source_document_id: '',
            score: 0.0,
          },
        ]
      }

      if (contextChunks.length === 0 && !ragFailed) {
        await c.env.DB.prepare(
          'INSERT INTO threshold_notifications (id, professor_id, query, created_at) VALUES (?1, ?2, ?3, ?4)',
        )
          .bind(uuid(), professor.id, transcript, nowIso())
          .run()

        const relaxed = await retrieveContext(c.env, transcript, professor.collection, {
          topK: 1,
          minScore: 0.0,
        })
        if (relaxed.length > 0) {
          contextChunks = relaxed
          lowRelevance = true
        }
      }

      const history = historyToMessages(await getHistory(c.env.DB, sessionId))
      try {
        responseText = await generateResponse(
          c.env,
          professor,
          history,
          transcript,
          contextChunks,
          { lowRelevance },
        )
      } catch (err) {
        console.error('LLM generation failed:', err)
        return c.json(
          { detail: 'El profesor está pensando... Intenta de nuevo.', step: 'llm' },
          503,
        )
      }
    }
  }

  const contextSources = contextChunks
    .map((chunk) => ({
      document_id: chunk.source_document_id,
      document_name: chunk.source_document,
      relevance_score: chunk.score ?? null,
      snippet: (chunk.text ?? '').slice(0, 200),
      page_number: chunk.source_page ?? null,
    }))
    .filter((s) => s.document_id || s.document_name)
  const sourcesJson = contextSources.length > 0 ? JSON.stringify(contextSources) : null

  const timestamp = nowIso()
  await c.env.DB.batch([
    c.env.DB.prepare(
      `INSERT INTO messages (id, session_id, role, content, audio_path, sources_json, timestamp)
       VALUES (?1, ?2, 'student', ?3, NULL, NULL, ?4)`,
    ).bind(uuid(), sessionId, transcript, timestamp),
    c.env.DB.prepare(
      `INSERT INTO messages (id, session_id, role, content, audio_path, sources_json, timestamp)
       VALUES (?1, ?2, 'professor', ?3, NULL, ?4, ?5)`,
    ).bind(uuid(), sessionId, responseText, sourcesJson, timestamp),
  ])

  if (!transcript) {
    return c.json({ text: responseText, audio: null })
  }

  const maxChars = int(c.env, 'TTS_MAX_TOTAL_CHARS', 6000)
  const speechText = truncateForTtsText(responseText, maxChars)
  try {
    const result = await synthesize(c.env, speechText, {
      language: responseLang,
    })
    if (result.ok) {
      const body =
        result.audio instanceof Uint8Array
          ? (() => {
              const bytes = new Uint8Array(result.audio.byteLength)
              bytes.set(result.audio)
              return bytes.buffer
            })()
          : result.audio
      return new Response(body, {
        status: 200,
        headers: {
          'Content-Type': 'audio/mpeg',
          ...(result.audio instanceof Uint8Array
            ? { 'Content-Length': String(result.audio.byteLength) }
            : {}),
        },
      })
    }
  } catch {
    // fall through to text-only
  }
  return c.json({ text: responseText, audio: null })
})

app.post('/:sessionId/local-avatar-connect', async (c) => {
  const session = await getSessionOrNull(c.env.DB, c.req.param('sessionId'))
  if (!session || session.ended_at) return c.json({ detail: 'Session not found or already ended' }, 404)
  return c.json({ status: 'ok', session_id: session.id })
})

app.post('/:sessionId/compress', async (c) => {
  const sessionId = c.req.param('sessionId')
  const budget = int(c.env, 'SESSION_MEMORY_MESSAGES', 10)
  const history = await getHistory(c.env.DB, sessionId)
  const removed = Math.max(0, history.length - budget)
  return c.json({ removed, session_id: sessionId })
})

app.get('/:sessionId/history', async (c) => {
  const history = await getHistory(c.env.DB, c.req.param('sessionId'))
  return c.json(history.map(messageResponse))
})

app.delete('/:sessionId', async (c) => {
  const sessionId = c.req.param('sessionId')
  const session = await getSessionOrNull(c.env.DB, sessionId)
  if (!session) return c.json({ detail: 'Session not found' }, 404)
  await c.env.DB.prepare('UPDATE sessions SET ended_at = ?1 WHERE id = ?2')
    .bind(nowIso(), sessionId)
    .run()
  return c.body(null, 204)
})

app.get('/:sessionId/messages/:messageId/sources', async (c) => {
  const { sessionId, messageId } = c.req.param()
  const msg = await c.env.DB.prepare(
    'SELECT * FROM messages WHERE id = ?1 AND session_id = ?2',
  )
    .bind(messageId, sessionId)
    .first<MessageRow>()
  if (!msg) return c.json({ detail: 'Message not found in session' }, 404)
  if (!msg.sources_json) return c.json({ sources: [] })
  try {
    const sources = JSON.parse(msg.sources_json)
    return c.json({ sources })
  } catch {
    return c.json({ sources: [] })
  }
})

export default app
