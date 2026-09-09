-- Virtual Professor — D1 schema (SQLite)
-- Mirrors the FastAPI/SQLAlchemy models.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  hashed_password TEXT NOT NULL,
  name          TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'student',
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  TEXT NOT NULL UNIQUE,
  expires_at  TEXT NOT NULL,
  is_revoked  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id);

CREATE TABLE IF NOT EXISTS students (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  email      TEXT NOT NULL UNIQUE,
  language   TEXT NOT NULL DEFAULT 'en',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS professors (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  topic         TEXT NOT NULL,
  language      TEXT NOT NULL,
  avatar_id     TEXT NOT NULL,
  collection    TEXT NOT NULL UNIQUE,
  system_prompt TEXT NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
  id            TEXT PRIMARY KEY,
  professor_id  TEXT NOT NULL REFERENCES professors(id) ON DELETE CASCADE,
  filename      TEXT NOT NULL,
  format        TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending',
  chunk_count   INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  uploaded_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_professor ON documents(professor_id);

CREATE TABLE IF NOT EXISTS sessions (
  id           TEXT PRIMARY KEY,
  student_id   TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  professor_id TEXT NOT NULL REFERENCES professors(id) ON DELETE CASCADE,
  started_at   TEXT NOT NULL,
  ended_at     TEXT,
  credits_used REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_sessions_student ON sessions(student_id);

CREATE TABLE IF NOT EXISTS messages (
  id          TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role        TEXT NOT NULL,
  content     TEXT NOT NULL,
  audio_path  TEXT,
  sources_json TEXT,
  timestamp   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);

CREATE TABLE IF NOT EXISTS threshold_notifications (
  id           TEXT PRIMARY KEY,
  professor_id TEXT NOT NULL REFERENCES professors(id) ON DELETE CASCADE,
  query        TEXT NOT NULL,
  created_at   TEXT NOT NULL
);