import { API_BASE } from '@/lib/api-base'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface AuthUser {
  id: string
  email: string
  name: string
  role: string
  is_active: boolean
  created_at: string
}

export interface LoginCredentials {
  email: string
  password: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: AuthUser
}

async function fetchWithRetry(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const delays = [0, 500, 1500]
  let lastError: unknown

  for (const delay of delays) {
    if (delay > 0) await new Promise(resolve => setTimeout(resolve, delay))
    try {
      return await fetch(input, init)
    } catch (error) {
      lastError = error
    }
  }

  throw lastError instanceof Error ? lastError : new Error('No se pudo conectar con el servidor.')
}

async function authError(res: Response, fallback: string): Promise<Error> {
  const body = await res.json().catch(() => null)
  const detail = body?.detail
  const error = body?.error

  let message = fallback
  if (typeof detail === 'string') message = detail
  else if (Array.isArray(detail) && detail[0]?.msg) message = detail[0].msg
  else if (typeof error === 'string') message = error
  else if (typeof error?.message === 'string') message = error.message

  return new Error(message)
}

// ── Token storage ─────────────────────────────────────────────────────────────

const ACCESS_KEY = 'vp_access_token'
const REFRESH_KEY = 'vp_refresh_token'

export function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(ACCESS_KEY)
}

function getRefreshToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(REFRESH_KEY)
}

function storeTokens(pair: TokenPair): void {
  localStorage.setItem(ACCESS_KEY, pair.access_token)
  localStorage.setItem(REFRESH_KEY, pair.refresh_token)
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

// ── API calls ─────────────────────────────────────────────────────────────────

export async function login(credentials: LoginCredentials): Promise<{ user: AuthUser; tokens: TokenPair }> {
  const res = await fetchWithRetry(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(credentials),
  })
  if (!res.ok) {
    throw await authError(res, 'Login failed')
  }
  const data: LoginResponse = await res.json()
  storeTokens(data)
  return {
    user: data.user,
    tokens: { access_token: data.access_token, refresh_token: data.refresh_token, token_type: data.token_type },
  }
}

export async function register(data: { email: string; password: string; name: string }): Promise<AuthUser> {
  const res = await fetchWithRetry(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    throw await authError(res, 'Registration failed')
  }
  return res.json()
}

export async function refreshTokens(): Promise<TokenPair | null> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return null

  const res = await fetchWithRetry(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  if (!res.ok) {
    clearTokens()
    return null
  }
  const data: TokenPair = await res.json()
  storeTokens(data)
  return data
}

export async function fetchMe(): Promise<AuthUser | null> {
  const token = getAccessToken()
  if (!token) return null

  const doFetch = (bearer: string) =>
    fetchWithRetry(`${API_BASE}/auth/me`, { headers: { Authorization: `Bearer ${bearer}` } })

  let res = await doFetch(token)

  if (res.status === 401) {
    const refreshed = await refreshTokens()
    if (!refreshed) {
      clearTokens()
      return null
    }
    res = await doFetch(refreshed.access_token)
  }

  if (!res.ok) {
    clearTokens()
    return null
  }

  return res.json()
}

export function logout(): void {
  clearTokens()
}
