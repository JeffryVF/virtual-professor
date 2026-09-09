import { unzipSync } from 'fflate'

import type { Env, DocumentRow } from '../types'
import { itemKey, uploadItem } from '../cloudflare'
import { int, uuid } from '../utils'

export interface ValidationOk {
  ok: true
  format: string
  content: Uint8Array
  contentType: string
  uploadName: string
}

export interface ValidationError {
  ok: false
  status: number
  code: string
  message: string
}

export type ValidationResult = ValidationOk | ValidationError

export const ALLOWED_EXTENSIONS = new Set(['pdf', 'docx', 'pptx', 'txt', 'url'])

const MIME = new Map<string, string>([
  ['pdf', 'application/pdf'],
  ['docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
  ['pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'],
  ['txt', 'text/plain'],
  ['url', 'text/plain'],
])

export function detectMagicFormat(data: Uint8Array): string | null {
  if (data.byteLength >= 5) {
    const head = new TextDecoder().decode(data.slice(0, 5))
    if (head === '%PDF-') return 'pdf'
  }
  if (data.byteLength >= 4) {
    const zipMagic = [data[0], data[1]]
    if (zipMagic[0] === 0x50 && zipMagic[1] === 0x4b) {
      const name = findZipEntryName(data.slice(0, 4096)) ?? ''
      if (name.includes('word/')) return 'docx'
      if (name.includes('ppt/')) return 'pptx'
    }
  }
  return null
}

function findZipEntryName(head: Uint8Array): string | null {
  // Look for "[Content_Types].xml" style filenames in the local header bytes.
  const text = new TextDecoder('utf-8', { fatal: false }).decode(head)
  if (text.includes('[Content_Types].xml') && text.includes('word/')) return 'word/'
  if (text.includes('[Content_Types].xml') && text.includes('ppt/')) return 'ppt/'
  return null
}

export async function validateUpload(
  env: Env,
  filename: string,
  file: Uint8Array,
  maxSizeMb: number,
  allowedFormats: Set<string>,
): Promise<ValidationResult> {
  const ext = (filename.split('.').pop() ?? '').toLowerCase()
  if (!allowedFormats.has(ext)) {
    return {
      ok: false,
      status: 400,
      code: 'EXTENSION_NOT_ALLOWED',
      message: `File extension '${ext}' is not allowed. Allowed: ${[...allowedFormats].join(', ')}.`,
    }
  }

  if (['pdf', 'docx', 'pptx'].includes(ext)) {
    const magic = detectMagicFormat(file)
    if (magic !== ext) {
      return {
        ok: false,
        status: 400,
        code: 'INVALID_FILE_TYPE',
        message: `File content does not match its extension (expected ${ext.toUpperCase()}).`,
      }
    }
  }

  if (file.byteLength > maxSizeMb * 1024 * 1024) {
    return {
      ok: false,
      status: 413,
      code: 'FILE_TOO_LARGE',
      message: `File is larger than ${maxSizeMb} MB. Cloudflare AI Search rejects larger files.`,
    }
  }

  return { ok: true, format: ext, content: file, contentType: MIME.get(ext) ?? 'application/octet-stream', uploadName: filename }
}

export function countPdfPages(data: Uint8Array): number {
  // Rough count of page objects: "/Type /Page" not "/Type /Pages".
  const text = new TextDecoder('utf-8', { fatal: false }).decode(data)
  const matches = text.match(/\/Type\s*\/Page[^s]/g)
  return matches ? matches.length : 0
}

export function isPdfPasswordProtected(data: Uint8Array): boolean {
  const text = new TextDecoder('utf-8', { fatal: false }).decode(data.slice(0, 2048))
  return /\/Encrypt\s+\d+\s+\d+\s+R/.test(text)
}

export function extractPptxText(data: Uint8Array): string {
  try {
    const zip = unzipSync(data)
    const entries = Object.entries(zip)
      .filter(([name]) => /^ppt\/slides\/slide[^/]*\.xml$/.test(name))
      .sort(([a], [b]) => {
        const na = Number.parseInt(a.match(/slide(\d+)/)?.[1] ?? '0', 10)
        const nb = Number.parseInt(b.match(/slide(\d+)/)?.[1] ?? '0', 10)
        return na - nb
      })
    const texts: string[] = []
    const decoder = new TextDecoder('utf-8')
    for (const [, content] of entries) {
      const xml = decoder.decode(content)
      for (const match of xml.matchAll(/<a:t>([^<]*)<\/a:t>/g)) {
        texts.push(match[1])
      }
    }
    return texts.join('\n')
  } catch {
    return ''
  }
}

export async function fetchUrlContent(url: string): Promise<{ body: Uint8Array; contentType: string }> {
  const response = await fetch(url, {
    redirect: 'follow',
    signal: AbortSignal.timeout(30000),
  })
  if (!response.ok) throw new Error(`URL fetch failed (${response.status})`)
  const body = new Uint8Array(await response.arrayBuffer())
  const contentType = (response.headers.get('content-type') ?? 'text/html').split(';')[0].trim()
  return { body, contentType }
}

export interface UploadPayload {
  key: string
  content: Uint8Array
  contentType: string
}

export async function prepareUploadPayload(
  env: Env,
  document: Pick<DocumentRow, 'id' | 'filename' | 'format'>,
  collection: string,
  file: Uint8Array,
  fileFormat: string,
  fetchUrl: boolean,
): Promise<UploadPayload> {
  let content = file
  let contentType = MIME.get(fileFormat) ?? 'application/octet-stream'
  let uploadName = document.filename

  if (fileFormat === 'url' && fetchUrl) {
    const url = new TextDecoder('utf-8').decode(file).trim()
    const fetched = await fetchUrlContent(url)
    content = fetched.body
    contentType = fetched.contentType
    const stem = document.filename.replace(/\.url$/i, '')
    uploadName = /\.(html|htm|txt|md)$/i.test(document.filename)
      ? document.filename
      : `${stem}.html`
    if (!contentType.includes('html') && !contentType.startsWith('text/')) {
      contentType = 'text/html'
    }
    return { key: itemKey(collection, document.id, uploadName), content, contentType }
  }

  if (fileFormat === 'pptx') {
    const text = extractPptxText(file)
    if (!text.trim()) {
      throw new Error('EMPTY_CHUNKS: Document produced no usable text content')
    }
    content = new TextEncoder().encode(text)
    contentType = 'text/plain'
    const stem = document.filename.replace(/\.pptx$/i, '')
    uploadName = `${stem}.txt`
  }

  return { key: itemKey(collection, document.id, uploadName), content, contentType }
}

export const professorCollection = (): string => `prof_${uuid().replace(/-/g, '').slice(0, 12)}`

export const maxPages = (env: Env): number => int(env, 'UPLOAD_MAX_PAGES', 400)