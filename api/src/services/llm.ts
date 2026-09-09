import type { Env } from '../types'
import type { ContextChunk } from './rag'
import { int, num } from '../utils'

export interface MemoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ProfessorLike {
  topic: string
  language: string
  collection: string
  system_prompt: string
}

const ZAI_BASE_DEFAULT = 'https://api.z.ai/api/paas/v4'

interface ChatResponse {
  choices?: { message?: { content?: string } }[]
}

async function chatCompletion(
  env: Env,
  messages: { role: string; content: string }[],
  options: { model?: string; maxTokens?: number; temperature?: number; timeoutMs?: number } = {},
): Promise<string> {
  const base = (env.ZAI_BASE_URL || ZAI_BASE_DEFAULT).replace(/\/$/, '')
  const url = `${base}/chat/completions`
  const models = [options.model ?? env.ZAI_LLM_MODEL, env.ZAI_FALLBACK_LLM_MODEL]
    .filter((m, i, arr) => m && arr.indexOf(m) === i)
  const maxTokens = options.maxTokens ?? int(env, 'LLM_MAX_TOKENS', 350)
  const body = {
    model: models[0],
    messages,
    thinking: { type: 'disabled' },
    max_tokens: maxTokens,
    temperature: options.temperature ?? 0.6,
    stream: false,
  }

  let attempt = 0
  for (const model of models) {
    if (body.model !== model) body.model = model
    for (let i = 0; i < 2; i++) {
      attempt++
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${env.ZAI_API_KEY}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(options.timeoutMs ?? 60000),
      })
      if (response.status === 429) {
        const delayMs = Math.min(4000, 1000 * Math.pow(2, attempt))
        await new Promise((resolve) => setTimeout(resolve, delayMs))
        continue
      }
      if (!response.ok) throw new Error(`Z.AI request failed (${response.status})`)
      const data = (await response.json()) as ChatResponse
      const content = data.choices?.[0]?.message?.content?.trim() ?? ''
      return content
    }
  }
  throw new Error('Z.AI exhausted retries (429)')
}

function languageInstruction(language: string): string {
  if (language === 'es') {
    return 'Responde SIEMPRE en español, sin mezclar inglés ni otros idiomas. Usa un tono natural y cercano.'
  }
  if (language === 'en') {
    return 'Always respond in English only, without mixing Spanish or other languages. Use a natural and friendly tone.'
  }
  return ''
}

function buildSystemPrompt(prof: ProfessorLike, lowRelevance: boolean): string {
  const languageInstructionText = languageInstruction(prof.language)
  const lowRelevanceInstruction = lowRelevance
    ? 'The retrieved material below is the closest match available but may not fully answer the question. Use it as best you can, or say you do not have enough information.'
    : ''
  return `${prof.system_prompt}

Use the following knowledge to answer the student's question. If the answer is not in the knowledge, say you don't have that information.

${languageInstructionText}

Cuando uses información de las fuentes, indica el documento usando la etiqueta [Source: ...] que aparece antes del texto. No inventes fuentes para fragmentos sin etiqueta.

Responde de forma breve y directa, idealmente 1 a 3 frases. Tu respuesta se usará para síntesis de voz, así que debe ser concisa y natural al hablar. Si el estudiante pide más detalles, puedes ampliar, pero por defecto sé breve.

${lowRelevanceInstruction}`.trim()
}

function buildUserMessage(
  history: MemoryMessage[],
  query: string,
  contextChunks: ContextChunk[],
): string {
  const conversation = history
    .map((m) => `${m.role}: ${m.content}`)
    .join('\n')
  const sources = contextChunks
    .map((c) => {
      const label = c.source_document
        ? `[Source: ${c.source_document}]\n`
        : ''
      const text = c.text ?? ''
      return `${label}${text}`.trimEnd()
    })
    .join('\n\n---\n\n')
  return `Conversation so far:
${conversation}

Student question: ${query}

Knowledge:
${sources}
`.trim()
}

export async function generateResponse(
  env: Env,
  prof: ProfessorLike,
  history: MemoryMessage[],
  query: string,
  contextChunks: ContextChunk[],
  options: { lowRelevance?: boolean; timeoutMs?: number } = {},
): Promise<string> {
  if (contextChunks.length === 0) {
    return prof.language === 'es'
      ? 'No encontré información sobre eso en mis fuentes'
      : 'I couldn\'t find information about that in my sources.'
  }
  const system = buildSystemPrompt(prof, options.lowRelevance ?? false)
  const user = buildUserMessage(history, query, contextChunks)
  return chatCompletion(env, [
    { role: 'system', content: system },
    { role: 'user', content: user },
  ], { timeoutMs: options.timeoutMs })
}

const STOPWORDS = new Set([
  'de', 'la', 'el', 'los', 'las', 'y', 'a', 'en', 'es', 'para', 'por',
  'con', 'no', 'que', 'del', 'al', 'un', 'una', 'the', 'of', 'to', 'and',
  'is', 'in', 'for', 'on', 's', 't', 'se', 'lo', 'le', 'o', 'como', 'cuando',
])

const DOMAIN_KEYWORDS: Record<string, string[]> = {
  programación: ['código', 'codigo', 'programa', 'python', 'javascript', 'funcion', 'function', 'variable', 'bucles', 'bug', 'clase', 'objeto', 'debug'],
  calculus: ['derivada', 'derivative', 'integral', 'limite', 'limit', 'funcion', 'function', 'grafica', 'graph'],
}

export async function isInScope(env: Env, topic: string, query: string, options: { timeoutMs?: number } = {}): Promise<boolean> {
  const topicLower = topic.toLowerCase().trim()
  const queryLower = query.toLowerCase().trim()

  if (topicLower && queryLower.includes(topicLower)) return true

  const topicKeywords = topicLower.split(/\s+/).filter((w) => w.length > 2 && !STOPWORDS.has(w))
  if (topicKeywords.some((kw) => queryLower.includes(kw))) return true

  for (const [domainKey, words] of Object.entries(DOMAIN_KEYWORDS)) {
    if (topicLower.includes(domainKey) && words.some((w) => queryLower.includes(w))) return true
  }

  try {
    const answer = await chatCompletion(
      env,
      [
        {
          role: 'system',
          content: 'You are a classifier. Determine if the student\'s question is about the professor\'s topic. Answer YES or NO only.',
        },
        {
          role: 'user',
          content: `Topic: ${topic.slice(0, 200)}\nStudent: ${query}\nIs this about ${topic.slice(0, 200)}? YES or NO:`,
        },
      ],
      { maxTokens: 8, timeoutMs: options.timeoutMs ?? 30000 },
    )
    return answer.toUpperCase().startsWith('YES')
  } catch {
    return true
  }
}

export function detectLanguage(text: string): 'es' | 'en' {
  const esHints = /[áéíóúñ¿¡ü]/i
  const esWords = ['el', 'la', 'los', 'las', 'es', 'un', 'una', 'que', 'de', 'para', 'por', 'con', 'y', 'en', 'como']
  const enWords = ['the', 'is', 'are', 'to', 'of', 'and', 'in', 'with', 'for', 'this', 'that', 'you']
  const lower = text.toLowerCase()
  if (esHints.test(text)) return 'es'
  const count = (words: string[]) => words.filter((w) => new RegExp(`\\b${w}\\b`).test(lower)).length
  return count(esWords) >= count(enWords) ? 'es' : 'en'
}

export function resolveLanguage(profLanguage: string, transcript: string): string {
  if (profLanguage === 'es' || profLanguage === 'en') return profLanguage
  return detectLanguage(transcript)
}

export function truncateForTts(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text
  const slice = text.slice(0, maxChars)
  const boundaries = ['. ', '? ', '! ']
  let cut = -1
  for (const b of boundaries) {
    const idx = slice.lastIndexOf(b)
    if (idx > cut) cut = idx
  }
  if (cut === -1) cut = slice.lastIndexOf(' ')
  return cut > 0 ? slice.slice(0, cut + (slice[cut] === ' ' ? 0 : 1)) : slice
}

export const memoryBudget = (env: Env): number => num(env, 'SESSION_MEMORY_MAX_TOKENS', 4096)

export function historyToMessages(rows: { role: string; content: string }[]): MemoryMessage[] {
  return rows
    .map((r) => ({ role: (r.role === 'student' ? 'user' : 'assistant') as 'user' | 'assistant', content: r.content }))
    .slice(0, Math.max(1, rows.length - 1))
}