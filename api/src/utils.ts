import type { Env } from './types'

export const int = (env: Env, name: keyof Env, fallback: number): number => {
  const raw = String(env[name] ?? '')
  const parsed = Number.parseInt(raw, 10)
  return Number.isFinite(parsed) ? parsed : fallback
}

export const num = (env: Env, name: keyof Env, fallback: number): number => {
  const raw = String(env[name] ?? '')
  const parsed = Number.parseFloat(raw)
  return Number.isFinite(parsed) ? parsed : fallback
}

export const bool = (env: Env, name: keyof Env, fallback = false): boolean => {
  const raw = String(env[name] ?? '').trim().toLowerCase()
  if (raw === '') return fallback
  return ['1', 'true', 'yes', 'on'].includes(raw)
}

export const corsOrigins = (env: Env): string[] => {
  const raw = (env.CORS_ORIGINS ?? '').trim()
  if (!raw) return ['http://localhost:3000']
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.map((o) => String(o).replace(/\/$/, ''))
  } catch {
    // fall through to comma-split
  }
  return raw.split(',').map((o) => o.trim().replace(/\/$/, '')).filter(Boolean)
}

export const nowIso = (): string => new Date().toISOString()

export const uuid = (): string => crypto.randomUUID()

export function randomHex(bytes = 32): string {
  const arr = new Uint8Array(bytes)
  crypto.getRandomValues(arr)
  return [...arr].map((b) => b.toString(16).padStart(2, '0')).join('')
}

export const sha256Hex = async (text: string): Promise<string> => {
  const data = new TextEncoder().encode(text)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

export const padDate = (value: string, target: string): string => value || target

export const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value))

export const firstError = (message: string, code?: string) => ({
  detail: { error: { code: code ?? 'ERROR', message } },
})