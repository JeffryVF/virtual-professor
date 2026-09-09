import { SELF, env, applyD1Migrations } from 'cloudflare:test'
import { expect } from 'vitest'
import initSql from '../migrations/0001_init.sql?raw'

export const BASE = 'https://virtual-professor.test'

export function api(path: string): string {
  return `${BASE}${path}`
}

export const json = { 'Content-Type': 'application/json' }

export function bearer(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` }
}

export function adminHeaders(key = 'test-admin-key'): Record<string, string> {
  return { 'X-Admin-Key': key }
}

export async function migrate(): Promise<void> {
  const db = (env as unknown as { DB: D1Database }).DB
  await applyD1Migrations(db, [{ name: '0001_init', queries: [initSql] }])
}

export async function registerUser(email: string, password: string, name: string): Promise<void> {
  const res = await SELF.fetch(api('/auth/register'), {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ email, password, name }),
  })
  expect(res.status).toBe(201)
}

export async function login(
  email: string,
  password: string,
): Promise<{ access_token: string; refresh_token: string }> {
  const res = await SELF.fetch(api('/auth/login'), {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ email, password }),
  })
  expect(res.status).toBe(200)
  return (await res.json()) as { access_token: string; refresh_token: string }
}