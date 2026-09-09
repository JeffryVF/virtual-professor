export interface Env {
  DB: D1Database
  UPLOADS?: R2Bucket
  AI?: {
    run: (model: string, inputs: Record<string, unknown>) => Promise<unknown>
  }
  CLOUDFLARE_ACCOUNT_ID: string
  CLOUDFLARE_API_TOKEN: string
  CLOUDFLARE_AI_SEARCH_INSTANCE: string
  GEMINI_API_KEY: string
  GEMINI_BASE_URL: string
  GEMINI_LLM_MODEL: string
  GEMINI_FALLBACK_LLM_MODEL: string
  LLM_MAX_TOKENS: string
  JWT_SECRET_KEY: string
  JWT_ALGORITHM?: string
  JWT_ACCESS_TOKEN_EXPIRE_MINUTES: string
  JWT_REFRESH_TOKEN_EXPIRE_DAYS: string
  ADMIN_API_KEY: string
  ADMIN_EMAIL: string
  ADMIN_PASSWORD: string
  ADMIN_NAME: string
  RAG_MIN_RELEVANCE_SCORE: string
  RAG_RETRIEVAL_TOP_K: string
  UPLOAD_MAX_SIZE_MB: string
  UPLOAD_MAX_PAGES: string
  UPLOAD_ALLOWED_FORMATS: string
  PROFESSOR_MAX_DOCUMENTS: string
  SESSION_MEMORY_MESSAGES: string
  SESSION_MEMORY_MAX_TOKENS: string
  SESSION_TIMEOUT_MINUTES: string
  TTS_MODEL_ES: string
  TTS_MODEL_EN: string
  TTS_MAX_TOTAL_CHARS: string
  CORS_ORIGINS: string
  DEBUG: string
}

export interface UserRow {
  id: string
  email: string
  hashed_password: string
  name: string
  role: string
  is_active: number
  created_at: string
}

export interface RefreshTokenRow {
  id: string
  user_id: string
  token_hash: string
  expires_at: string
  is_revoked: number
  created_at: string
}

export interface StudentRow {
  id: string
  name: string
  email: string
  language: string
  created_at: string
}

export interface ProfessorRow {
  id: string
  name: string
  topic: string
  language: string
  avatar_id: string
  collection: string
  system_prompt: string
  created_at: string
}

export interface DocumentRow {
  id: string
  professor_id: string
  filename: string
  format: string
  status: string
  chunk_count: number
  error_message: string | null
  uploaded_at: string
}

export interface SessionRow {
  id: string
  student_id: string
  professor_id: string
  started_at: string
  ended_at: string | null
  credits_used: number
}

export interface MessageRow {
  id: string
  session_id: string
  role: string
  content: string
  audio_path: string | null
  sources_json: string | null
  timestamp: string
}
