import type { Env } from './types'

const API_BASE = 'https://api.cloudflare.com/client/v4'

export const MAX_FILE_BYTES = 4 * 1024 * 1024
const SEARCH_MAX_RESULTS = 50

export class CloudflareAISearchError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'CloudflareAISearchError'
  }
}

export function isConfigured(env: Env): boolean {
  return Boolean(
    env.CLOUDFLARE_ACCOUNT_ID &&
      env.CLOUDFLARE_API_TOKEN &&
      env.CLOUDFLARE_AI_SEARCH_INSTANCE,
  )
}

export function itemKey(collection: string, documentId: string, filename: string): string {
  const safeName = filename.replace(/\\/g, '/').split('/').pop() || 'document'
  return `${collection}/${documentId}/${safeName}`
}

export function parseItemKey(key: string): { collection: string; documentId: string; filename: string } {
  const parts = key.split('/')
  if (parts.length >= 3) return { collection: parts[0], documentId: parts[1], filename: parts[parts.length - 1] }
  if (parts.length === 2) return { collection: parts[0], documentId: '', filename: parts[1] }
  return { collection: '', documentId: '', filename: key }
}

export function folderStartsWithFilter(prefix: string): Record<string, Record<string, string>> {
  const normalized = prefix.endsWith('/') ? prefix : `${prefix}/`
  return { folder: { $gte: normalized, $lt: `${normalized.slice(0, -1)}0` } }
}

function instanceUrl(env: Env, path = ''): string {
  const base = `${API_BASE}/accounts/${env.CLOUDFLARE_ACCOUNT_ID}/ai-search/instances/${env.CLOUDFLARE_AI_SEARCH_INSTANCE}`
  return path ? `${base}/${path.replace(/^\//, '')}` : base
}

function authHeaders(env: Env): Record<string, string> {
  return { Authorization: `Bearer ${env.CLOUDFLARE_API_TOKEN}` }
}

function requireConfigured(env: Env): void {
  if (!isConfigured(env)) {
    throw new CloudflareAISearchError(
      'Cloudflare AI Search is not configured. Set CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, and CLOUDFLARE_AI_SEARCH_INSTANCE.',
    )
  }
}

function unwrap<T>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'result' in payload) {
    const p = payload as Record<string, unknown>
    if (p.success === false) {
      throw new CloudflareAISearchError(`Cloudflare AI Search error: ${JSON.stringify(p.errors ?? p.error ?? p)}`)
    }
    return p.result as T
  }
  return payload as T
}

export async function getInstance(env: Env, timeoutMs = 60000): Promise<Record<string, unknown>> {
  requireConfigured(env)
  try {
    const response = await fetch(instanceUrl(env), {
      headers: authHeaders(env),
      signal: AbortSignal.timeout(timeoutMs),
    })
    if (!response.ok) {
      const body = await response.text().catch(() => '')
      throw new CloudflareAISearchError(`Cloudflare instance probe failed (${response.status}): ${body.slice(0, 300)}`)
    }
    const result = unwrap<unknown>(await response.json())
    if (result && typeof result === 'object') return result as Record<string, unknown>
    return { id: env.CLOUDFLARE_AI_SEARCH_INSTANCE }
  } catch (err) {
    if (err instanceof CloudflareAISearchError) throw err
    return { id: env.CLOUDFLARE_AI_SEARCH_INSTANCE, probe_error: String(err) }
  }
}

export async function uploadItem(
  env: Env,
  key: string,
  content: Uint8Array,
  contentType: string,
  timeoutMs = 60000,
): Promise<Record<string, unknown>> {
  requireConfigured(env)
  if (content.byteLength > MAX_FILE_BYTES) {
    throw new CloudflareAISearchError(
      `FILE_TOO_LARGE: Cloudflare AI Search rejects files over 4 MB (${content.byteLength} bytes)`,
    )
  }
  const form = new FormData()
  form.append('wait_for_completion', 'true')
  form.append('file', new Blob([content as BlobPart], { type: contentType }), key)
  const response = await fetch(instanceUrl(env, 'items'), {
    method: 'POST',
    headers: authHeaders(env),
    body: form,
    signal: AbortSignal.timeout(timeoutMs),
  })
  if (!response.ok) throw new CloudflareAISearchError(`Cloudflare upload failed (${response.status})`)
  const payload = (await response.json()) as Record<string, unknown>
  return unwrap<Record<string, unknown>>(payload)
}

export async function listItems(env: Env, timeoutMs = 60000): Promise<Record<string, unknown>[]> {
  requireConfigured(env)
  const items: Record<string, unknown>[] = []
  let page = 1
  for (;;) {
    const url = new URL(instanceUrl(env, 'items'))
    url.searchParams.set('page', String(page))
    url.searchParams.set('per_page', '50')
    url.searchParams.set('source', 'builtin')
    const response = await fetch(url.toString(), {
      headers: authHeaders(env),
      signal: AbortSignal.timeout(timeoutMs),
    })
    if (!response.ok) throw new CloudflareAISearchError(`Cloudflare list failed (${response.status})`)
    const payload = (await response.json()) as Record<string, unknown>
    const result = unwrap<unknown>(payload)
    const batch = asItemList(result)
    items.push(...batch)
    const info = (payload.result_info ?? {}) as Record<string, unknown>
    const total = info.total_count
    if (!batch.length || (typeof total === 'number' && items.length >= total)) break
    if (batch.length < 50) break
    page += 1
  }
  return items
}

export async function deleteItem(env: Env, itemId: string, timeoutMs = 60000): Promise<void> {
  requireConfigured(env)
  const response = await fetch(instanceUrl(env, `items/${encodeURIComponent(itemId)}`), {
    method: 'DELETE',
    headers: authHeaders(env),
    signal: AbortSignal.timeout(timeoutMs),
  })
  if (!response.ok) throw new CloudflareAISearchError(`Cloudflare delete failed (${response.status})`)
}

export interface SearchOptions {
  folderPrefix?: string
  maxNumResults?: number
  timeoutMs?: number
}

export async function search(
  env: Env,
  query: string,
  options: SearchOptions = {},
): Promise<Record<string, unknown>[]> {
  requireConfigured(env)
  const envTopK = Number.parseInt(env.RAG_RETRIEVAL_TOP_K ?? '8', 10)
  const fallback = Number.isFinite(envTopK) ? envTopK : 8
  const limit = Math.min(SEARCH_MAX_RESULTS, Math.max(1, options.maxNumResults ?? fallback))
  const body: Record<string, unknown> = {
    query: query || ' ',
    ai_search_options: {
      retrieval: { max_num_results: limit },
    },
  }
  if (options.folderPrefix) {
    ;(body.ai_search_options as Record<string, Record<string, unknown>>).retrieval.filters =
      folderStartsWithFilter(options.folderPrefix)
  }
  const response = await fetch(instanceUrl(env, 'search'), {
    method: 'POST',
    headers: { ...authHeaders(env), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(options.timeoutMs ?? 60000),
  })
  if (!response.ok) throw new CloudflareAISearchError(`Cloudflare search failed (${response.status})`)
  const payload = (await response.json()) as Record<string, unknown>
  const result = unwrap<unknown>(payload)
  if (Array.isArray(result)) return result.filter((c) => typeof c === 'object' && c !== null) as Record<string, unknown>[]
  if (result && typeof result === 'object') {
    const chunks = (result as Record<string, unknown>).chunks ?? (result as Record<string, unknown>).data
    if (Array.isArray(chunks)) return chunks.filter((c) => typeof c === 'object' && c !== null) as Record<string, unknown>[]
  }
  return []
}

export async function deleteItemsByPrefix(env: Env, prefix: string): Promise<number> {
  if (!isConfigured(env)) return 0
  const items = await listItems(env)
  const targets = items.filter((item) => {
    const key = String(item.key ?? '')
    return key.startsWith(prefix.endsWith('/') ? prefix : `${prefix}/`)
  })
  for (const item of targets) {
    const id = String(item.id ?? '')
    if (id) await deleteItem(env, id)
  }
  return targets.length
}

function asItemList(result: unknown): Record<string, unknown>[] {
  if (Array.isArray(result)) return result.filter((c) => typeof c === 'object' && c !== null) as Record<string, unknown>[]
  if (result && typeof result === 'object') {
    const r = result as Record<string, unknown>
    for (const key of ['items', 'data', 'objects']) {
      const nested = r[key]
      if (Array.isArray(nested)) return nested.filter((c) => typeof c === 'object' && c !== null) as Record<string, unknown>[]
    }
    if ('id' in r || 'key' in r) return [r]
  }
  return []
}