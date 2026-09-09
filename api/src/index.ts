import { Hono } from 'hono'
import type { Context as HonoContext } from 'hono'
import { cors } from 'hono/cors'

import type { Context } from './context'
import type { Env } from './types'
import { corsOrigins, nowIso, uuid } from './utils'
import { hashPassword } from './security'

import health from './routes/health'
import auth from './routes/auth'
import professors from './routes/professors'
import sessions from './routes/sessions'
import admin from './routes/admin'
import avatars from './routes/avatars'

const app = new Hono<Context>()

// ── CORS ────────────────────────────────────────────────────────────────────
app.use('*', async (c, next) => {
  const origins = corsOrigins(c.env)
  const handshake = cors({
    origin: origins.length === 1 && origins[0] === '*'
      ? (origin) => origin ?? '*'
      : origins,
    allowMethods: ['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
    allowHeaders: ['Content-Type', 'Authorization', 'X-Admin-Key'],
    credentials: !(origins.length === 1 && origins[0] === '*'),
    maxAge: 600,
  })
  return handshake(c, next)
})

// ── Security headers ────────────────────────────────────────────────────────
app.use('*', async (c, next) => {
  await next()
  c.res.headers.set('X-Content-Type-Options', 'nosniff')
  c.res.headers.set('X-Frame-Options', 'SAMEORIGIN')
  c.res.headers.set('X-XSS-Protection', '1; mode=block')
  c.res.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin')
})

// ── Simple in-memory rate limiting (per isolate) ────────────────────────────
const RATE_LIMITS: Record<string, { limit: number; windowMs: number }> = {
  '/auth/login': { limit: 5, windowMs: 60000 },
  '/auth/refresh': { limit: 3, windowMs: 60000 },
  '/auth/register': { limit: 2, windowMs: 60000 },
}
const hits = new Map<string, number[]>()

async function rateLimit(c: HonoContext<Context>, next: () => Promise<void>) {
  const path = new URL(c.req.url).pathname
  const rule = RATE_LIMITS[path]
  if (!rule) return next()
  const forwarded = c.req.header('CF-Connecting-IP')
  const key = `${path}:${forwarded ?? 'unknown'}`
  const now = Date.now()
  const windowStart = now - rule.windowMs
  const recent = (hits.get(key) ?? []).filter((t) => t > windowStart)
  if (recent.length >= rule.limit) {
    const retry = Math.max(1, Math.ceil((recent[0] - windowStart) / 1000))
    return c.json(
      { error: `Demasiadas solicitudes. Intente de nuevo en ${retry} segundos.`, retry_after_seconds: retry },
      429,
    )
  }
  recent.push(now)
  hits.set(key, recent)
  return next()
}
app.use('/auth/*', rateLimit)

// ── Routers ─────────────────────────────────────────────────────────────────
app.route('/', health)
app.route('/auth', auth)
app.route('/professors', professors)
app.route('/sessions', sessions)
app.route('/admin', admin)
app.route('/avatars', avatars)

app.get('/', (c) => c.json({ service: 'virtual-professor-api', status: 'ok' }))
app.notFound((c) => c.json({ detail: 'Not Found' }, 404))

// ── Seed default admin user (idempotent, best-effort) ───────────────────────
async function seedAdmin(env: Env): Promise<void> {
  if (!env.ADMIN_EMAIL || !env.ADMIN_PASSWORD) return
  const email = env.ADMIN_EMAIL.trim().toLowerCase()
  const existing = await env.DB.prepare('SELECT id FROM users WHERE email = ?1').bind(email).first()
  if (existing) return
  await env.DB.prepare(
    `INSERT INTO users (id, email, hashed_password, name, role, is_active, created_at)
     VALUES (?1, ?2, ?3, ?4, 'admin', 1, ?5)`,
  )
    .bind(uuid(), email, await hashPassword(env.ADMIN_PASSWORD), env.ADMIN_NAME || 'Administrator', nowIso())
    .run()
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    void ctx
    await seedAdmin(env).catch(() => undefined)
    return app.fetch(request, env)
  },
}