import { Hono } from 'hono'
import type { Context as HonoContext } from 'hono'

import type { Context } from '../context'
import {
  createRefreshToken,
  findRefreshToken,
  getJwtUser,
  getUserById,
  hashPassword,
  revokeAllUserTokens,
  signAccessToken,
  verifyPassword,
} from '../security'
import { nowIso, uuid } from '../utils'
import type { UserRow } from '../types'

const app = new Hono<Context>()

export function userResponse(user: UserRow) {
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    role: user.role,
    is_active: user.is_active === 1,
    created_at: user.created_at,
  }
}

async function loginForUser(c: HonoContext<Context>, user: UserRow) {
  const accessToken = await signAccessToken(c.env, user)
  const refreshToken = await createRefreshToken(c.env.DB, c.env, user.id)
  return c.json({
    access_token: accessToken,
    refresh_token: refreshToken,
    token_type: 'bearer',
    user: userResponse(user),
  })
}

app.post('/register', async (c) => {
  const body = await c.req.json().catch(() => null)
  const email = typeof body?.email === 'string' ? body.email.trim().toLowerCase() : ''
  const password = typeof body?.password === 'string' ? body.password : ''
  const name = typeof body?.name === 'string' ? body.name.trim() : ''
  const role = typeof body?.role === 'string' ? body.role : 'student'

  if (role !== 'student') {
    return c.json({ detail: 'Public registration is limited to student accounts' }, 403)
  }
  if (!email || !name || password.length < 8 || password.length > 128) {
    return c.json(
      { detail: [{ loc: ['body'], msg: 'Invalid registration payload', type: 'value_error' }] },
      422,
    )
  }

  const existing = await c.env.DB.prepare('SELECT id FROM users WHERE email = ?1').bind(email).first()
  if (existing) return c.json({ detail: 'Email already registered' }, 409)

  const user = {
    id: uuid(),
    email,
    hashed_password: await hashPassword(password),
    name,
    role,
    is_active: 1,
    created_at: nowIso(),
  }
  const inserted = await c.env.DB.prepare(
    `INSERT INTO users (id, email, hashed_password, name, role, is_active, created_at)
     VALUES (?1, ?2, ?3, ?4, ?5, 1, ?6)`,
  )
    .bind(user.id, user.email, user.hashed_password, user.name, user.role, user.created_at)
    .run()
  if (!inserted.success) return c.json({ detail: 'Email already registered' }, 409)

  return c.json(userResponse(user), 201)
})

app.post('/login', async (c) => {
  const body = await c.req.json().catch(() => null)
  const email = typeof body?.email === 'string' ? body.email.trim().toLowerCase() : ''
  const password = typeof body?.password === 'string' ? body.password : ''

  const user = await c.env.DB.prepare('SELECT * FROM users WHERE email = ?1').bind(email).first<UserRow>()
  if (!user || !(await verifyPassword(password, user.hashed_password))) {
    return c.json({ detail: 'Invalid email or password' }, 401)
  }
  if (user.is_active !== 1) {
    return c.json({ detail: 'User account is inactive' }, 403)
  }
  return loginForUser(c, user)
})

app.post('/refresh', async (c) => {
  const body = await c.req.json().catch(() => null)
  const rawToken = typeof body?.refresh_token === 'string' ? body.refresh_token : ''

  const stored = await findRefreshToken(c.env.DB, rawToken)
  if (!stored) return c.json({ detail: 'Invalid refresh token' }, 401)

  const now = new Date()
  if (stored.is_revoked === 1) {
    await revokeAllUserTokens(c.env.DB, stored.user_id)
    return c.json({ detail: 'Refresh token has been revoked. All sessions have been invalidated.' }, 401)
  }
  if (new Date(stored.expires_at) < now) {
    await c.env.DB.prepare('UPDATE refresh_tokens SET is_revoked = 1 WHERE id = ?1').bind(stored.id).run()
    return c.json({ detail: 'Refresh token has expired' }, 401)
  }

  const user = await getUserById(c.env.DB, stored.user_id)
  if (!user || user.is_active !== 1) {
    await c.env.DB.prepare('UPDATE refresh_tokens SET is_revoked = 1 WHERE id = ?1').bind(stored.id).run()
    return c.json({ detail: 'User not found or inactive' }, 401)
  }

  await c.env.DB.prepare('UPDATE refresh_tokens SET is_revoked = 1 WHERE id = ?1').bind(stored.id).run()

  return loginForUser(c, user)
})

app.get('/me', async (c) => {
  const user = await getJwtUser(c.env.DB, c.env, c.req.header('Authorization'))
  if (!user) {
    return c.json({ detail: 'Not authenticated' }, 401)
  }
  if (user.is_active !== 1) return c.json({ detail: 'User is inactive' }, 403)
  return c.json(userResponse(user))
})

export default app