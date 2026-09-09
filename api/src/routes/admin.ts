import { Hono } from 'hono'
import type { Context as HonoContext } from 'hono'

import type { Context } from '../context'
import type { DocumentRow, Env, ProfessorRow, SessionRow, MessageRow } from '../types'
import { int, nowIso, uuid } from '../utils'
import { getJwtUser } from '../security'
import { deleteItemsByPrefix, uploadItem } from '../cloudflare'
import { professorResponse, buildProfessor } from './professors'
import {
  ALLOWED_EXTENSIONS,
  countPdfPages,
  isPdfPasswordProtected,
  prepareUploadPayload,
  validateUpload,
} from '../services/ingest'

const app = new Hono<Context>()

export function documentResponse(d: DocumentRow) {
  return {
    id: d.id,
    professor_id: d.professor_id,
    filename: d.filename,
    format: d.format,
    status: d.status,
    chunk_count: d.chunk_count,
    error_message: d.error_message,
    uploaded_at: d.uploaded_at,
  }
}

async function adminOrKey(c: HonoContext<Context>): Promise<boolean> {
  const authHeader = c.req.header('Authorization')
  if (authHeader?.startsWith('Bearer ')) {
    const user = await getJwtUser(c.env.DB, c.env, authHeader)
    if (user && user.role === 'admin' && user.is_active === 1) return true
  }
  const adminKey = c.req.header('X-Admin-Key')
  if (adminKey && c.env.ADMIN_API_KEY && adminKey === c.env.ADMIN_API_KEY) return true
  return false
}

app.use('*', async (c, next) => {
  if (!(await adminOrKey(c))) {
    return c.json({ detail: 'Admin access required' }, 403)
  }
  await next()
})

async function getProfessorRow(db: D1Database, id: string): Promise<ProfessorRow | null> {
  return (await db.prepare('SELECT * FROM professors WHERE id = ?1').bind(id).first<ProfessorRow>()) ?? null
}

async function getDocumentRow(db: D1Database, id: string): Promise<DocumentRow | null> {
  return (await db.prepare('SELECT * FROM documents WHERE id = ?1').bind(id).first<DocumentRow>()) ?? null
}

// ── Professors ──────────────────────────────────────────────────────────────

app.post('/professors', async (c) => {
  const body = await c.req.json().catch(() => null)
  if (
    typeof body?.name !== 'string' ||
    typeof body?.topic !== 'string' ||
    typeof body?.system_prompt !== 'string' ||
    !['es', 'en', 'both'].includes(body.language)
  ) {
    return c.json({ detail: [{ loc: ['body'], msg: 'Invalid professor payload', type: 'value_error' }] }, 422)
  }
  const prof = buildProfessor({
    name: body.name,
    topic: body.topic,
    language: body.language,
    avatar_id: typeof body.avatar_id === 'string' ? body.avatar_id : undefined,
    system_prompt: body.system_prompt,
  })
  await c.env.DB.prepare(
    `INSERT INTO professors (id, name, topic, language, avatar_id, collection, system_prompt, created_at)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)`,
  )
    .bind(prof.id, prof.name, prof.topic, prof.language, prof.avatar_id, prof.collection, prof.system_prompt, prof.created_at)
    .run()
  return c.json(professorResponse(prof), 201)
})

app.get('/professors', async (c) => {
  const { results } = await c.env.DB.prepare('SELECT * FROM professors ORDER BY created_at ASC').all<ProfessorRow>()
  return c.json(results.map(professorResponse))
})

app.get('/professors/:id', async (c) => {
  const prof = await getProfessorRow(c.env.DB, c.req.param('id'))
  if (!prof) return c.json({ detail: 'Professor not found' }, 404)
  return c.json(professorResponse(prof))
})

app.patch('/professors/:id', async (c) => {
  const prof = await getProfessorRow(c.env.DB, c.req.param('id'))
  if (!prof) return c.json({ detail: 'Professor not found' }, 404)
  const body = await c.req.json().catch(() => null)
  const updates = {
    name: typeof body?.name === 'string' ? body.name : null,
    topic: typeof body?.topic === 'string' ? body.topic : null,
    language: ['es', 'en', 'both'].includes(body?.language) ? body.language : null,
    avatar_id: typeof body?.avatar_id === 'string' ? body.avatar_id : null,
    system_prompt: typeof body?.system_prompt === 'string' ? body.system_prompt : null,
  }
  const entries = Object.entries(updates).filter(([, v]) => v !== null)
  if (entries.length > 0) {
    const clauses = entries.map(([k], i) => `${k} = ?${i + 1}`).join(', ')
    const values = entries.map(([, v]) => v)
    await c.env.DB.prepare(`UPDATE professors SET ${clauses} WHERE id = ?${entries.length + 1}`)
      .bind(...values, prof.id)
      .run()
  }
  const updated = await getProfessorRow(c.env.DB, prof.id)
  return c.json(professorResponse(updated!))
})

app.delete('/professors/:id', async (c) => {
  const prof = await getProfessorRow(c.env.DB, c.req.param('id'))
  if (!prof) return c.json({ detail: 'Professor not found' }, 404)
  await deleteItemsByPrefix(c.env, prof.collection)
  await c.env.DB.prepare('DELETE FROM professors WHERE id = ?1').bind(prof.id).run()
  return c.body(null, 204)
})

// ── Documents ───────────────────────────────────────────────────────────────

app.post('/professors/:id/documents', async (c) => {
  const prof = await getProfessorRow(c.env.DB, c.req.param('id'))
  if (!prof) return c.json({ detail: 'Professor not found' }, 404)

  const { results: allDocs } = await c.env.DB.prepare(
    'SELECT * FROM documents WHERE professor_id = ?1',
  ).bind(prof.id).all<DocumentRow>()
  const maxDocs = int(c.env, 'PROFESSOR_MAX_DOCUMENTS', 100)
  if (allDocs.length >= maxDocs) {
    return c.json(
      {
        detail: `Professor already has ${allDocs.length} documents (max: ${maxDocs}). Remove existing documents before uploading new ones.`,
      },
      409,
    )
  }
  const hasProcessing = allDocs.some((d) => d.status === 'processing')
  if (hasProcessing) {
    return c.json(
      { detail: 'Another document is currently being processed for this professor. Wait for processing to complete before uploading another.' },
      409,
    )
  }

  const formData = await c.req.formData().catch(() => null)
  const file = formData?.get('file')
  if (!(file instanceof File)) return c.json({ detail: 'Missing file upload field' }, 400)

  const bytes = new Uint8Array(await file.arrayBuffer())
  const maxSizeMb = int(c.env, 'UPLOAD_MAX_SIZE_MB', 4)
  const allowed = new Set(
    (c.env.UPLOAD_ALLOWED_FORMATS || 'pdf,docx,pptx,txt,url')
      .split(',')
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  )
  const validation = await validateUpload(c.env, file.name, bytes, maxSizeMb, allowed)
  if (!validation.ok) {
    return c.json(
      { detail: { error: { code: validation.code, message: validation.message } } },
      validation.status as 400 | 413,
    )
  }

  const document: DocumentRow = {
    id: uuid(),
    professor_id: prof.id,
    filename: file.name,
    format: validation.format,
    status: 'processing',
    chunk_count: 0,
    error_message: null,
    uploaded_at: nowIso(),
  }
  await c.env.DB.prepare(
    `INSERT INTO documents (id, professor_id, filename, format, status, chunk_count, error_message, uploaded_at)
     VALUES (?1, ?2, ?3, ?4, 'processing', 0, NULL, ?5)`,
  )
    .bind(document.id, document.professor_id, validation.uploadName, validation.format, document.uploaded_at)
    .run()

  try {
    await runIngestion(c.env, prof.collection, document, validation.content, validation.format)
    const done = await getDocumentRow(c.env.DB, document.id)
    if (done) return c.json(documentResponse(done), 201)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    document.status = 'error'
    document.error_message = message
    await c.env.DB.prepare('UPDATE documents SET status = ?1, error_message = ?2 WHERE id = ?3')
      .bind('error', message, document.id)
      .run()
    const done = await getDocumentRow(c.env.DB, document.id)
    if (done) return c.json(documentResponse(done), 201)
  }
  return c.json(documentResponse(document), 201)
})

async function runIngestion(
  env: Env,
  collection: string,
  document: Pick<DocumentRow, 'id' | 'filename' | 'format'>,
  file: Uint8Array,
  fileFormat: string,
): Promise<void> {
  const maxChunksPages = int(env, 'UPLOAD_MAX_PAGES', 400)

  if (fileFormat === 'pdf') {
    if (isPdfPasswordProtected(file)) {
      throw new Error('PDF_PASSWORD_PROTECTED: PDF is password protected')
    }
    const pages = countPdfPages(file)
    if (pages > maxChunksPages) {
      throw new Error(`PDF_TOO_MANY_PAGES: PDF has ${pages} pages, maximum is ${maxChunksPages}`)
    }
  }

  const payload = await prepareUploadPayload(env, document, collection, file, fileFormat, true)
  const result = await uploadItem(env, payload.key, payload.content, payload.contentType)

  if (env.UPLOADS) {
    await env.UPLOADS.put(payload.key, payload.content, {
      httpMetadata: { contentType: payload.contentType },
    }).catch(() => undefined)
  }

  const statusField = String(result.status ?? '')
  if (statusField === 'error') {
    throw new Error(`Cloudflare indexing error: ${JSON.stringify(result)}`)
  }
  const chunkCount =
    typeof result.chunks_count === 'number'
      ? result.chunks_count
      : typeof result.chunk_count === 'number'
        ? result.chunk_count
        : 0
  await env.DB.prepare('UPDATE documents SET status = ?1, chunk_count = ?2, error_message = NULL WHERE id = ?3')
    .bind('ready', chunkCount, document.id)
    .run()
}

app.get('/professors/:id/documents', async (c) => {
  const { results } = await c.env.DB.prepare(
    'SELECT * FROM documents WHERE professor_id = ?1 ORDER BY uploaded_at DESC',
  )
    .bind(c.req.param('id'))
    .all<DocumentRow>()
  return c.json(results.map(documentResponse))
})

app.delete('/documents/:id', async (c) => {
  const doc = await getDocumentRow(c.env.DB, c.req.param('id'))
  if (!doc) return c.json({ detail: 'Document not found' }, 404)
  const prof = await getProfessorRow(c.env.DB, doc.professor_id)
  if (prof) {
    await deleteItemsByPrefix(c.env, `${prof.collection}/${doc.id}`)
  }
  await c.env.DB.prepare('DELETE FROM documents WHERE id = ?1').bind(doc.id).run()
  return c.body(null, 204)
})

app.get('/documents/:id/chunks', async (c) => {
  const doc = await getDocumentRow(c.env.DB, c.req.param('id'))
  if (!doc) return c.json({ detail: 'Document not found' }, 404)
  if (doc.status !== 'ready') {
    return c.json({ detail: `Document status is '${doc.status}', expected 'ready'` }, 400)
  }
  const prof = await getProfessorRow(c.env.DB, doc.professor_id)
  if (!prof) return c.json({ detail: 'Professor not found' }, 404)

  const full = c.req.query('full') === 'true'
  const offset = Math.max(0, Number.parseInt(c.req.query('offset') ?? '0', 10) || 0)
  const limitRaw = Number.parseInt(c.req.query('limit') ?? '50', 10) || 50
  const limit = Math.min(200, Math.max(1, limitRaw))

  const { listDocumentChunks } = await import('../services/rag')
  const chunks = await listDocumentChunks(c.env, prof.collection, doc.id, doc.filename, { offset, limit })

  return c.json({
    document_id: doc.id,
    document_name: doc.filename,
    total_chunks: offset === 0 ? chunks.length : doc.chunk_count || offset + chunks.length,
    chunks: chunks.map((chunk, i) => ({
      chunk_index: offset + i,
      text: full ? chunk.text : chunk.text.slice(0, 500),
      score: chunk.score,
      page_number: chunk.pageLabel,
    })),
  })
})

app.post('/documents/:id/reindex', async (c) => {
  const doc = await getDocumentRow(c.env.DB, c.req.param('id'))
  if (!doc) return c.json({ detail: 'Document not found' }, 404)
  if (doc.status === 'pending' || doc.status === 'processing') {
    return c.json({ detail: `Cannot reindex document with status '${doc.status}'` }, 409)
  }
  const prof = await getProfessorRow(c.env.DB, doc.professor_id)
  if (!prof) return c.json({ detail: 'Professor not found' }, 404)

  await deleteItemsByPrefix(c.env, `${prof.collection}/${doc.id}`)

  const stored = await c.env.DB.prepare('SELECT format, filename FROM documents WHERE id = ?1')
    .bind(doc.id)
    .first<{ format: string; filename: string }>()

  let content: Uint8Array | null = null
  if (c.env.UPLOADS) {
    const original = await c.env.UPLOADS.get(`${prof.collection}/${doc.id}/${doc.filename}`)
    if (original && stored) {
      content = new Uint8Array(await original.arrayBuffer())
    }
  }
  if (!content) {
    return c.json({ detail: `SOURCE_MISSING: original file for ${doc.filename} is not available. Re-upload it from the admin UI.` }, 409)
  }

  await c.env.DB.prepare('UPDATE documents SET status = ?1, error_message = NULL, chunk_count = 0 WHERE id = ?2')
    .bind('processing', doc.id)
    .run()

  try {
    await runIngestion(c.env, prof.collection, { id: doc.id, filename: doc.filename, format: stored!.format }, content, stored!.format)
    return c.json({ status: 'reindexing', document_id: doc.id }, 202)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    await c.env.DB.prepare('UPDATE documents SET status = ?1, error_message = ?2 WHERE id = ?3')
      .bind('error', message, doc.id)
      .run()
    return c.json({ detail: message }, 500)
  }
})

app.get('/indexing/status', async (c) => {
  const { results: professors } = await c.env.DB.prepare('SELECT * FROM professors ORDER BY created_at ASC').all<ProfessorRow>()
  const { results: docs } = await c.env.DB.prepare('SELECT * FROM documents').all<DocumentRow>()

  const collections = professors.map((prof) => {
    const profDocs = docs.filter((d) => d.professor_id === prof.id)
    const byStatus: Record<string, number> = { pending: 0, processing: 0, ready: 0, error: 0 }
    for (const d of profDocs) byStatus[d.status] = (byStatus[d.status] ?? 0) + 1
    const readyDocs = profDocs.filter((d) => d.status === 'ready')
    return {
      professor_id: prof.id,
      professor_name: prof.name,
      collection: prof.collection,
      total_documents: profDocs.length,
      documents_by_status: byStatus,
      total_chunks: readyDocs.reduce((acc, d) => acc + d.chunk_count, 0),
      stored_chunks: readyDocs.reduce((acc, d) => acc + d.chunk_count, 0),
      last_indexed_at: readyDocs.length ? readyDocs[readyDocs.length - 1].uploaded_at : null,
      last_error: profDocs.find((d) => d.status === 'error')?.error_message ?? null,
    }
  })

  const totalChunks = collections.reduce((acc, c) => acc + c.total_chunks, 0)
  return c.json({
    collections,
    summary: {
      total_collections: collections.length,
      total_documents: docs.length,
      total_chunks: totalChunks,
      collections_with_errors: collections.filter((c) => c.documents_by_status.error > 0).length,
    },
  })
})

app.get('/sessions', async (c) => {
  const { results } = await c.env.DB.prepare('SELECT * FROM sessions ORDER BY started_at DESC').all<SessionRow>()
  return c.json(
    results.map((s) => ({
      id: s.id,
      student_id: s.student_id,
      professor_id: s.professor_id,
      started_at: s.started_at,
      ended_at: s.ended_at,
      credits_used: s.credits_used,
    })),
  )
})

app.get('/sessions/:id/history', async (c) => {
  const { results } = await c.env.DB.prepare('SELECT * FROM messages WHERE session_id = ?1 ORDER BY timestamp ASC')
    .bind(c.req.param('id'))
    .all<MessageRow>()
  return c.json(
    results.map((m) => ({
      id: m.id,
      session_id: m.session_id,
      role: m.role,
      content: m.content,
      audio_path: m.audio_path,
      sources_json: m.sources_json,
      timestamp: m.timestamp,
    })),
  )
})

export default app