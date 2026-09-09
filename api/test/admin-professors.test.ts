import { SELF } from 'cloudflare:test'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, json, adminHeaders, bearer, login, migrate } from './helpers'

function stubCloudflareFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string | URL) => {
      const u = String(url)
      if (u.includes('/ai-search/')) {
        return new Response(JSON.stringify({ success: true, result: { items: [] } }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      throw new Error(`Unexpected fetch in admin test: ${u}`)
    }),
  )
}

describe('admin (professors CRUD)', () => {
  beforeAll(async () => {
    await migrate()
  })

  beforeEach(() => {
    stubCloudflareFetch()
  })

  it('rejects requests without admin credentials', async () => {
    const res = await SELF.fetch(api('/admin/professors'))
    expect(res.status).toBe(403)
  })

  it('rejects an invalid admin key', async () => {
    const res = await SELF.fetch(api('/admin/professors'), { headers: adminHeaders('wrong-key') })
    expect(res.status).toBe(403)
  })

  it('creates a professor', async () => {
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
    const body = (await res.json()) as Record<string, unknown>
    expect(body.id).toBeTruthy()
    expect(body.name).toBe('Prof. IA')
    expect(body.topic).toBe('Inteligencia Artificial')
    expect(body.language).toBe('es')
    expect(body.avatar_id).toBeTruthy()
    expect(body.collection).toBeTruthy()
  })

  it('rejects an invalid professor payload', async () => {
    const res = await SELF.fetch(api('/admin/professors'), {
      method: 'POST',
      headers: { ...json, ...adminHeaders() },
      body: JSON.stringify({ name: 'X', topic: 'Y', language: 'xx', system_prompt: 'Z' }),
    })
    expect(res.status).toBe(422)
  })

  it('lists, gets, patches and deletes a professor', async () => {
    const create = await SELF.fetch(api('/admin/professors'), {
      method: 'POST',
      headers: { ...json, ...adminHeaders() },
      body: JSON.stringify({
        name: 'Prof. Cálculo',
        topic: 'Calculus',
        language: 'en',
        system_prompt: 'Answer about calculus.',
      }),
    })
    expect(create.status).toBe(201)
    const created = (await create.json()) as { id: string }

    const list = await SELF.fetch(api('/admin/professors'), { headers: adminHeaders() })
    expect(list.status).toBe(200)
    const items = (await list.json()) as { id: string }[]
    expect(items.some((p) => p.id === created.id)).toBe(true)

    const get = await SELF.fetch(api(`/admin/professors/${created.id}`), { headers: adminHeaders() })
    expect(get.status).toBe(200)
    expect(((await get.json()) as { id: string }).id).toBe(created.id)

    const patch = await SELF.fetch(api(`/admin/professors/${created.id}`), {
      method: 'PATCH',
      headers: { ...json, ...adminHeaders() },
      body: JSON.stringify({ name: 'Prof. Cálculo Avanzado' }),
    })
    expect(patch.status).toBe(200)
    expect(((await patch.json()) as { name: string }).name).toBe('Prof. Cálculo Avanzado')

    const del = await SELF.fetch(api(`/admin/professors/${created.id}`), {
      method: 'DELETE',
      headers: adminHeaders(),
    })
    expect(del.status).toBe(204)

    const after = await SELF.fetch(api(`/admin/professors/${created.id}`), { headers: adminHeaders() })
    expect(after.status).toBe(404)
  })

  it('accepts an admin JWT bearer', async () => {
    const { access_token } = await login('admin@test.com', 'adminpass123')
    const res = await SELF.fetch(api('/admin/professors'), { headers: bearer(access_token) })
    expect(res.status).toBe(200)
  })
})