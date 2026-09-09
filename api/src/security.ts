import { jwtVerify, SignJWT } from 'jose'

import type { Env, RefreshTokenRow, UserRow } from './types'
import { int, nowIso, sha256Hex, uuid } from './utils'

const PBKDF2_ITERATIONS = 100_000
const PBKDF2_KEY_BYTES = 32
const PBKDF2_SALT_BYTES = 16

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}

async function pbkdf2Hash(plain: string, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
  const keyMaterial = await crypto.subtle.importKey('raw', new TextEncoder().encode(plain), 'PBKDF2', false, [
    'deriveBits',
  ])
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt: salt as unknown as BufferSource, iterations },
    keyMaterial,
    PBKDF2_KEY_BYTES * 8,
  )
  return new Uint8Array(bits)
}

function timingSafeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i]
  return diff === 0
}

export async function hashPassword(plain: string): Promise<string> {
  const salt = crypto.getRandomValues(new Uint8Array(PBKDF2_SALT_BYTES))
  const key = await pbkdf2Hash(plain, salt, PBKDF2_ITERATIONS)
  return `pbkdf2$${PBKDF2_ITERATIONS}$${bytesToBase64(salt)}$${bytesToBase64(key)}`
}

export async function verifyPassword(plain: string, stored: string): Promise<boolean> {
  try {
    const match = /^pbkdf2\$(\d+)\$([A-Za-z0-9+/=]+)\$([A-Za-z0-9+/=]+)$/.exec(stored)
    if (!match) return false
    const [, iterationsStr, saltB64, hashB64] = match
    const salt = base64ToBytes(saltB64)
    const expected = base64ToBytes(hashB64)
    const actual = await pbkdf2Hash(plain, salt, Number.parseInt(iterationsStr, 10))
    return timingSafeEqual(actual, expected)
  } catch {
    return false
  }
}

export async function signAccessToken(env: Env, user: Pick<UserRow, 'id' | 'role'>): Promise<string> {
  const secret = new TextEncoder().encode(env.JWT_SECRET_KEY)
  const minutes = int(env, 'JWT_ACCESS_TOKEN_EXPIRE_MINUTES', 30)
  return new SignJWT({ sub: user.id, role: user.role })
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuedAt()
    .setExpirationTime(`${minutes}m`)
    .setJti(uuid())
    .sign(secret)
}

export interface AccessTokenClaims {
  sub: string
  role: string
  exp?: number
  iat?: number
  jti?: string
}

export async function verifyAccessToken(env: Env, token: string): Promise<AccessTokenClaims | null> {
  try {
    const secret = new TextEncoder().encode(env.JWT_SECRET_KEY)
    const { payload } = await jwtVerify(token, secret, { algorithms: ['HS256'] })
    if (typeof payload.sub !== 'string') return null
    return payload as unknown as AccessTokenClaims
  } catch {
    return null
  }
}

export async function createRefreshToken(
  db: D1Database,
  env: Env,
  userId: string,
): Promise<string> {
  const raw = uuid()
  const hash = await sha256Hex(raw)
  const days = int(env, 'JWT_REFRESH_TOKEN_EXPIRE_DAYS', 7)
  const expiresAt = new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString()
  await db
    .prepare(
      `INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, is_revoked, created_at)
       VALUES (?, ?, ?, ?, 0, ?)`,
    )
    .bind(uuid(), userId, hash, expiresAt, nowIso())
    .run()
  return raw
}

export async function findRefreshToken(db: D1Database, raw: string): Promise<RefreshTokenRow | null> {
  const hash = await sha256Hex(raw)
  const result = await db
    .prepare('SELECT * FROM refresh_tokens WHERE token_hash = ?1')
    .bind(hash)
    .first<RefreshTokenRow>()
  return result ?? null
}

export async function revokeAllUserTokens(db: D1Database, userId: string): Promise<void> {
  await db
    .prepare('UPDATE refresh_tokens SET is_revoked = 1 WHERE user_id = ?1')
    .bind(userId)
    .run()
}

export async function getUserById(db: D1Database, id: string): Promise<UserRow | null> {
  const row = await db.prepare('SELECT * FROM users WHERE id = ?1').bind(id).first<UserRow>()
  return row ?? null
}

export async function getJwtUser(
  db: D1Database,
  env: Env,
  authHeader: string | null | undefined,
): Promise<UserRow | null> {
  if (!authHeader?.startsWith('Bearer ')) return null
  const claims = await verifyAccessToken(env, authHeader.slice('Bearer '.length).trim())
  if (!claims) return null
  return getUserById(db, claims.sub)
}