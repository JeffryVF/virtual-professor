import { Hono } from 'hono'

import type { Context } from '../context'
import type { ProfessorRow } from '../types'
import { nowIso, uuid } from '../utils'
import { professorCollection } from '../services/ingest'

const app = new Hono<Context>()

export function professorResponse(p: ProfessorRow) {
  return {
    id: p.id,
    name: p.name,
    topic: p.topic,
    language: p.language,
    avatar_id: p.avatar_id,
    collection: p.collection,
    system_prompt: p.system_prompt,
    created_at: p.created_at,
  }
}

app.get('', async (c) => {
  const { results } = await c.env.DB.prepare(
    'SELECT * FROM professors ORDER BY created_at ASC',
  ).all<ProfessorRow>()
  return c.json(results.map(professorResponse))
})

app.get('/:id', async (c) => {
  const id = c.req.param('id')
  const prof = await c.env.DB.prepare('SELECT * FROM professors WHERE id = ?1').bind(id).first<ProfessorRow>()
  if (!prof) return c.json({ detail: 'Professor not found' }, 404)
  return c.json(professorResponse(prof))
})

export function buildProfessor(
  data: { name: string; topic: string; language: string; avatar_id?: string; system_prompt: string },
): ProfessorRow {
  return {
    id: uuid(),
    name: data.name,
    topic: data.topic,
    language: data.language,
    avatar_id: data.avatar_id ?? '65f9e3c9-d48b-4118-b73a-4ae2e3cbb8f0',
    collection: professorCollection(),
    system_prompt: data.system_prompt,
    created_at: nowIso(),
  }
}

export default app