import { SELF } from 'cloudflare:test'
import { beforeAll, describe, expect, it } from 'vitest'
import { api, json, bearer, login, migrate } from './helpers'

describe('auth', () => {
  beforeAll(async () => {
    await migrate()
  })

  it('registers a student and rejects a duplicate email', async () => {
    const res = await SELF.fetch(api('/auth/register'), {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ email: 'alice@test.com', password: 'password123', name: 'Alice' }),
    })
    expect(res.status).toBe(201)
    const body = (await res.json()) as { email: string; role: string }
    expect(body.email).toBe('alice@test.com')
    expect(body.role).toBe('student')

    const dup = await SELF.fetch(api('/auth/register'), {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ email: 'alice@test.com', password: 'password123', name: 'Alice' }),
    })
    expect(dup.status).toBe(409)
  })

  it('runs the full login lifecycle for the seeded admin', async () => {
    const email = 'admin@test.com'
    const password = 'adminpass123'

    const wrong = await SELF.fetch(api('/auth/login'), {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ email, password: 'wrong-password' }),
    })
    expect(wrong.status).toBe(401)

    const { access_token, refresh_token } = await login(email, password)

    const me = await SELF.fetch(api('/auth/me'), { headers: bearer(access_token) })
    expect(me.status).toBe(200)
    const meBody = (await me.json()) as { email: string; role: string }
    expect(meBody.email).toBe(email)
    expect(meBody.role).toBe('admin')

    const refresh = await SELF.fetch(api('/auth/refresh'), {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ refresh_token }),
    })
    expect(refresh.status).toBe(200)
    expect(((await refresh.json()) as { access_token: string }).access_token).toBeTruthy()

    const reuse = await SELF.fetch(api('/auth/refresh'), {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ refresh_token }),
    })
    expect(reuse.status).toBe(401)
  })

  it('rejects /me without a token', async () => {
    const res = await SELF.fetch(api('/auth/me'))
    expect(res.status).toBe(401)
  })
})