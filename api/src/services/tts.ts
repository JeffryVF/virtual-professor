import type { Env } from '../types'

export interface TtsOptions {
  voice: string
  rate?: string
  pitch?: string
  volume?: string
}

export interface SynthesisResult {
  audio: Uint8Array | ReadableStream<Uint8Array>
  ok: boolean
}

const AURA_ES = '@cf/deepgram/aura-2-es'
const AURA_EN = '@cf/deepgram/aura-2-en'

function spanishVoice(voice: string): boolean {
  return voice.toLowerCase().startsWith('es')
}

function decodeBase64Audio(value: string): Uint8Array {
  const encoded = value.startsWith('data:') ? value.slice(value.indexOf(',') + 1) : value
  const binary = atob(encoded)
  const audio = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    audio[index] = binary.charCodeAt(index)
  }
  return audio
}

function isReadableAudioStream(result: unknown): result is ReadableStream<Uint8Array> {
  return (
    typeof result === 'object' &&
    result !== null &&
    'getReader' in result &&
    typeof result.getReader === 'function'
  )
}

async function readAudioResult(result: unknown): Promise<Uint8Array> {
  if (typeof result === 'string') return decodeBase64Audio(result)
  if (result instanceof Uint8Array) return result
  if (result instanceof ArrayBuffer) return new Uint8Array(result)
  if (isReadableAudioStream(result)) {
    const reader = result.getReader() as ReadableStreamDefaultReader<Uint8Array>
    const chunks: Uint8Array[] = []
    let total = 0
    for (;;) {
      const next = await reader.read()
      if (next.done) break
      const chunk = next.value instanceof Uint8Array ? next.value : new Uint8Array(next.value)
      chunks.push(chunk)
      total += chunk.byteLength
    }
    const audio = new Uint8Array(total)
    let offset = 0
    for (const chunk of chunks) {
      audio.set(chunk, offset)
      offset += chunk.byteLength
    }
    return audio
  }
  return new Uint8Array(0)
}

/**
 * Text-to-speech via Cloudflare Workers AI (@cf/deepgram/aura-2-*).
 * Aura-2 natively speaks Spanish/English and returns MP3 bytes (audio/mpeg),
 * matching the content type the frontend expects. Errors fall back to
 * text-only responses (ok: false).
 */
export async function synthesize(env: Env, text: string, options: TtsOptions): Promise<SynthesisResult> {
  if (!env.AI) {
    return { audio: new Uint8Array(0), ok: false }
  }
  try {
    const model = spanishVoice(options.voice) ? AURA_ES : AURA_EN
    const result = await env.AI.run(model, {
      text,
      encoding: 'mp3',
    })
    if (isReadableAudioStream(result)) return { audio: result, ok: true }
    const audio = await readAudioResult(result)
    return { audio, ok: audio.byteLength > 0 }
  } catch (error) {
    console.error('[tts] synthesis failed:', error)
    return { audio: new Uint8Array(0), ok: false }
  }
}