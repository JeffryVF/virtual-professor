# Virtual Professor

An AI-powered virtual professor system that lets students interact with avatar-based teachers via voice. Each professor is specialized in a specific topic and answers questions based on its own knowledge base. Built with LiveAvatar (LITE mode), RAG, and fully containerized with Docker.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Services](#services)
- [Data Models](#data-models)
- [Voice Interaction Flow](#voice-interaction-flow)
- [Document Ingestion Flow](#document-ingestion-flow)
- [API Endpoints](#api-endpoints)
- [Directory Structure](#directory-structure)
- [Docker Compose](#docker-compose)
- [Environment Variables](#environment-variables)
- [Open Items](#open-items)
- [Getting Started](#getting-started)

---

## Overview

- Admins create professors, each scoped to a specific topic (e.g., Mathematics, History, Biology)
- Admins upload knowledge documents in any format (PDF, DOCX, MP4, MP3, URLs, etc.)
- Students select a professor avatar and interact via voice in Spanish or English
- The avatar listens, retrieves relevant knowledge, and responds using a synchronized lip-synced avatar
- If a student asks something outside the professor's topic, the system redirects them politely
- All conversation history and student sessions are persisted

**LiveAvatar mode:** LITE (1 credit/min) — we own the full STT → RAG → LLM → TTS pipeline; LiveAvatar only renders the avatar.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         BROWSER (Student)                       │
│  ┌──────────────────┐        ┌──────────────────────────────┐   │
│  │  Student Portal  │        │   LiveAvatar Web SDK         │   │
│  │  (choose avatar) │        │   (WebRTC stream in/out)     │   │
│  └────────┬─────────┘        └──────────┬───────────────────┘   │
└───────────┼──────────────────────────── │ ─────────────────────┘
            │ REST                        │ WebRTC / Audio
            ▼                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      BACKEND  (FastAPI)                         │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │Session Router│  │ Admin Router │  │  LiveAvatar LITE      │  │
│  │  /sessions/* │  │  /admin/*    │  │  Connector           │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────┘  │
│         │                 │                                     │
│  ┌──────▼─────────────────▼──────────────────────────────────┐  │
│  │               Orchestrator (Agent)                         │  │
│  │   1. STT → 2. Scope Check → 3. RAG → 4. Reranker          │  │
│  │         → 5. LLM Prompt → 6. TTS                          │  │
│  │                           ┌──────────────────────────┐     │  │
│  │                           │  Langfuse Observability   │     │  │
│  │                           │  (traces every step)      │     │  │
│  │                           └──────────────────────────┘     │  │
│  └──────┬───────────┬──────────────────┬──────────┬──────────┘  │
└─────────┼───────────┼──────────────────┼──────────┼────────────┘
          │           │                  │          │
    ┌─────▼──┐  ┌─────▼──┐  ┌───────────▼──┐ ┌────▼────┐
    │Whisper │  │ Ollama │  │    Qdrant    │ │ Kokoro  │
    │  STT   │  │  LLM   │  │  Vector DB   │ │   TTS   │
    └────────┘  └────────┘  └──────┬───────┘ └─────────┘
                                   │
                            ┌──────▼──────┐   ┌─────────┐
                            │ BGE Reranker│   │  Redis  │
                            │  (local)    │   │(sessions│
                            └─────────────┘   │ cache)  │
                                              └─────────┘
                            ┌──────────────┐
                            │  PostgreSQL  │
                            │  (profiles,  │
                            │   history)   │
                            └──────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     BROWSER (Admin)                             │
│   Admin Portal  →  Upload docs / manage professors / view logs  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Services

| Service | Image | Port | Role |
|---|---|---|---|
| `backend` | custom FastAPI | 8000 | Orchestrator, REST API, session management |
| `frontend` | custom Next.js | 3000 | Student portal + Admin portal |
| `whisper` | `onerahmet/openai-whisper` | 9000 | Speech-to-Text (ES/EN) |
| `ollama` | `ollama/ollama` | 11434 | LLM inference (OpenAI-compatible API) |
| `qdrant` | `qdrant/qdrant` | 6333 | Vector database, per-professor collections |
| `kokoro` | custom wrapper | 8880 | Text-to-Speech (ES/EN voices) |
| `postgres` | `postgres:16` | 5432 | Students, professors, sessions, messages |
| `redis` | `redis:7` | 6379 | Active session context cache |
| `nginx` | `nginx` | 80/443 | Reverse proxy |

### Service Responsibilities

**backend (FastAPI)**
- Receives audio from the LiveAvatar SDK
- Orchestrates the full pipeline: STT → scope check → RAG → LLM → TTS
- Manages professors, documents, students, and sessions
- Runs document ingestion as background tasks

**whisper**
- Transcribes student audio to text
- Multilingual: auto-detects Spanish and English
- Model: `base` for speed, `small` or `medium` for accuracy

**ollama**
- Hosts the LLM locally (e.g., `llama3.2`, `mistral`)
- Also hosts the embedding model (`nomic-embed-text`) used for RAG
- Exposes OpenAI-compatible API at `/v1`

**qdrant**
- One collection per professor
- Stores document chunks with embeddings and metadata
- Supports filtering by professor, document, and language

**kokoro**
- Converts LLM response text to speech audio
- Supports distinct voices per professor
- Returns audio bytes sent directly to LiveAvatar LITE

**postgres**
- Stores all relational data: professors, documents, students, sessions, messages
- Source of truth for admin portal and reporting

**redis**
- Caches the last N messages per active session (short-term memory)
- Keyed by session_id, TTL aligned to session timeout

---

## Data Models

### professors
```
id             UUID        PRIMARY KEY
name           VARCHAR     professor display name
topic          VARCHAR     scope boundary (e.g., "Calculus", "World History")
language       ENUM        es | en | both
avatar_id      VARCHAR     LiveAvatar free avatar UUID
collection     VARCHAR     Qdrant collection name
system_prompt  TEXT        personality and tone instructions for the LLM
created_at     TIMESTAMP
```

### documents
```
id             UUID        PRIMARY KEY
professor_id   UUID        FOREIGN KEY → professors.id
filename       VARCHAR     original filename
format         VARCHAR     pdf | docx | pptx | txt | mp3 | mp4 | url | csv | json
status         ENUM        pending | processing | ready | error
chunk_count    INTEGER     number of chunks stored in Qdrant
error_message  TEXT        populated if status = error
uploaded_at    TIMESTAMP
```

### students
```
id             UUID        PRIMARY KEY
name           VARCHAR
email          VARCHAR     UNIQUE
language       ENUM        es | en
created_at     TIMESTAMP
```

### sessions
```
id             UUID        PRIMARY KEY
student_id     UUID        FOREIGN KEY → students.id
professor_id   UUID        FOREIGN KEY → professors.id
started_at     TIMESTAMP
ended_at       TIMESTAMP   NULL while active
credits_used   FLOAT       accumulated LiveAvatar LITE credits
```

### messages
```
id             UUID        PRIMARY KEY
session_id     UUID        FOREIGN KEY → sessions.id
role           ENUM        student | professor
content        TEXT        transcribed or generated text
audio_path     VARCHAR     optional path to stored audio file
timestamp      TIMESTAMP
```

---

## Voice Interaction Flow

```
1.  Student opens browser → selects professor avatar
2.  LiveAvatar Web SDK initializes WebRTC session (LITE mode)
3.  Student speaks → browser captures microphone audio
4.  Audio chunk → POST /sessions/{id}/speak (our backend)
5.  Whisper transcribes audio → text
6.  Redis: load last N messages (short-term memory / conversation context)
7.  LlamaIndex: embed query → retrieve top-k chunks from professor's Qdrant collection
8.  Scope check (LLM or keyword): is the query related to the professor's topic?
    ├── IN SCOPE  → build prompt (system_prompt + history + retrieved context + query)
    │              → Ollama LLM generates response text
    └── OUT OF SCOPE → static redirect: "Please ask questions related to [topic]."
9.  Response text → Kokoro TTS → audio bytes
10. Audio bytes returned to LiveAvatar LITE → avatar lip-syncs and speaks
11. Message pair (student + professor) saved to PostgreSQL
12. Redis: update session context with new exchange
```

**Short-term memory:** last 10 message pairs cached in Redis per session.
**Long-term memory:** full conversation history in PostgreSQL, available for future sessions.

---

## Document Ingestion Flow

```
Admin uploads file → POST /admin/professors/{id}/documents
    ↓
FastAPI BackgroundTask
    ↓
LlamaIndex reader (format-specific)
    ├── PDF/DOCX/PPTX/TXT  → SimpleDirectoryReader
    ├── MP3/MP4            → Whisper transcription → text
    ├── URL                → web scraper reader
    └── CSV/JSON           → structured reader
    ↓
Text extraction + cleaning
    ↓
Chunking: 512 tokens, 50 token overlap, metadata tagging
    ↓
Embedding: Ollama nomic-embed-text
    ↓
Upsert into professor's Qdrant collection
    ↓
Document status updated to "ready"
```

**Continuous updates:** documents can be re-uploaded at any time. Old chunks are removed and replaced. The professor's collection is always up to date.

---

## API Endpoints

### Admin Routes (`/admin`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/professors` | Create a new professor |
| `GET` | `/admin/professors` | List all professors |
| `GET` | `/admin/professors/{id}` | Get professor details |
| `PATCH` | `/admin/professors/{id}` | Update professor metadata |
| `DELETE` | `/admin/professors/{id}` | Delete professor and all data |
| `POST` | `/admin/professors/{id}/documents` | Upload document (any format) |
| `GET` | `/admin/professors/{id}/documents` | List professor's documents |
| `DELETE` | `/admin/documents/{id}` | Remove document and its Qdrant chunks |
| `GET` | `/admin/sessions` | List all sessions with usage stats |
| `GET` | `/admin/sessions/{id}/history` | Full conversation of a session |

### Student Routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/professors` | List available professors (public) |
| `GET` | `/professors/{id}` | Get professor info |
| `POST` | `/sessions/students` | Register student |
| `POST` | `/sessions` | Start a new session |
| `POST` | `/sessions/{id}/speak` | Send audio, receive audio response |
| `POST` | `/sessions/{id}/liveavatar-connect` | Exchange LiveAvatar token for session |
| `POST` | `/sessions/{id}/compress` | Compress completed session |
| `GET` | `/sessions/{id}/history` | Get conversation history |
| `DELETE` | `/sessions/{id}` | End session |

---

## Directory Structure

```
virtual-professor/
├── docker-compose.yml
├── docker-compose.override.yml       ← dev overrides (hot-reload, debug)
├── .env.example
├── README.md
├── AGENTS.md                         ← AI contributor guide
│
├── services/
│   ├── backend/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py                   ← FastAPI app entry point
│   │   ├── routers/
│   │   │   ├── admin.py              ← professor + document management
│   │   │   ├── sessions.py           ← voice session handling
│   │   │   └── professors.py         ← public professor listing
│   │   ├── services/
│   │   │   ├── stt.py                ← Whisper HTTP client
│   │   │   ├── tts.py                ← Kokoro HTTP client
│   │   │   ├── llm.py                ← Ollama client + prompt building
│   │   │   ├── rag.py                ← LlamaIndex + Qdrant retrieval
│   │   │   ├── reranker.py           ← BGE cross-encoder reranker
│   │   │   ├── memory.py             ← Redis session context manager
│   │   │   ├── ingestion.py          ← document processing pipeline
│   │   │   ├── liveavatar.py         ← LiveAvatar LITE connector
│   │   │   └── langfuse.py           ← Langfuse observability helpers
│   │   ├── models/
│   │   │   ├── db.py                 ← SQLAlchemy ORM models
│   │   │   └── schemas.py            ← Pydantic request/response schemas
│   │   ├── core/
│   │   │   ├── config.py             ← settings from environment variables
│   │   │   └── database.py           ← DB session factory
│   │   └── tests/
│   │       ├── conftest.py           ← pytest fixtures + test client
│   │       ├── test_rag.py           ← retrieval, reranker, context chunk tests
│   │       ├── test_llm.py           ← prompt building, [Source:] label tests
│   │       ├── test_sessions.py      ← session lifecycle + speak endpoint
│   │       └── test_validation.py    ← file upload validation tests
│   │
│   ├── frontend/
│   │   ├── Dockerfile
│   │   ├── package.json
│   │   ├── src/
│   │   │   ├── app/
│   │   │   │   ├── layout.tsx        ← root layout
│   │   │   │   ├── page.tsx          ← landing / professor selection
│   │   │   │   ├── session/
│   │   │   │   │   └── [id]/
│   │   │   │   │       └── page.tsx  ← live voice session with avatar
│   │   │   │   └── admin/
│   │   │   │       ├── page.tsx      ← admin dashboard
│   │   │   │       └── professors/
│   │   │   │           ├── page.tsx  ← professor management
│   │   │   │           └── [id]/
│   │   │   │               └── documents/
│   │   │   │                   └── page.tsx  ← document upload + status
│   │   │   ├── components/
│   │   │   │   ├── student/
│   │   │   │   │   ├── AvatarSession.tsx  ← LiveAvatar Web SDK wrapper
│   │   │   │   │   └── ProfessorCard.tsx  ← avatar selector UI
│   │   │   │   ├── admin/
│   │   │   │   │   ├── Sidebar.tsx
│   │   │   │   │   └── ProfessorForm.tsx
│   │   │   │   └── ui/               ← shadcn/ui components
│   │   │   └── lib/
│   │   │       └── api.ts            ← API client with auth headers
│   │   └── public/
│   │
│   └── kokoro/
│       ├── Dockerfile
│       ├── server.py                 ← FastAPI wrapper around Kokoro TTS
│       └── requirements.txt
│
├── data/
│   ├── uploads/                      ← raw uploaded files (mounted volume)
│   ├── qdrant/                       ← Qdrant persistent storage
│   └── postgres/                     ← PostgreSQL persistent storage
│
├── config/
│   └── nginx.conf                    ← reverse proxy routing
│
├── openspec/                         ← SDD change specifications (OpenSpec)
├── docs/
│   ├── troubleshooting.md            ← RAG pipeline issue tracking
│   └── plans/                        ← Implementation plans
│
└── RELEASE_CHECKLIST.md              ← Production release checklist
```

---

## Docker Compose

The stack is defined in [`docker-compose.yml`](./docker-compose.yml) at the repo root. It includes 9 services:

| Service | Image | Role |
|---------|-------|------|
| `nginx` | nginx:alpine | Reverse proxy |
| `frontend` | custom Node.js | Next.js app |
| `backend` | custom Python | FastAPI orchestrator |
| `whisper` | onerahmet/openai-whisper-asr-webservice | Speech-to-Text |
| `ollama` | ollama/ollama | LLM + embeddings |
| `qdrant` | qdrant/qdrant | Vector database |
| `kokoro` | custom Python | Text-to-Speech |
| `postgres` | postgres:16-alpine | Relational database |
| `redis` | redis:7-alpine | Session cache |

Development overrides (hot-reload, debug ports) live in `docker-compose.override.yml` and are applied automatically when you run `docker compose up`.

> ⚠️ The inline YAML previously shown here was always stale — see the actual [`docker-compose.yml`](./docker-compose.yml) for the source of truth.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values.

```env
# PostgreSQL
POSTGRES_USER=profesor
POSTGRES_PASSWORD=changeme
POSTGRES_DB=virtual_profesor
DATABASE_URL=postgresql://profesor:changeme@postgres:5432/virtual_profesor

# Redis
REDIS_URL=redis://redis:6379

# Qdrant
QDRANT_URL=http://qdrant:6333

# Ollama
OLLAMA_URL=http://ollama:11434
OLLAMA_LLM_MODEL=llama3.2
OLLAMA_EMBED_MODEL=nomic-embed-text

# Whisper
WHISPER_URL=http://whisper:9000

# Kokoro TTS
KOKORO_URL=http://kokoro:8880

# LiveAvatar
LIVEAVATAR_API_KEY=your_key_here
LIVEAVATAR_API_URL=https://api.liveavatar.com

# Admin
ADMIN_API_KEY=changeme

# Session memory
SESSION_MEMORY_MESSAGES=10
SESSION_TIMEOUT_MINUTES=30
```

---

## Open Items

| # | Item | Status | Notes |
|---|---|---|---|---|
| 1 | LiveAvatar API key + sandbox | Pending | Register at liveavatar.com to get key and test LITE mode |
| 2 | LLM model selection | Pending | Start with `llama3.2` (fast) or `mistral` (quality) |
| 3 | Kokoro voice selection | Pending | Pick ES + EN voices per professor or globally |
| 4 | GPU availability | Pending | Affects Whisper + Ollama speed significantly |
| 5 | Admin auth | **In progress** | See [plan 02](docs/plans/02-auth-backend.md) |
| 6 | Student auth | **In progress** | See [plan 03](docs/plans/03-auth-frontend.md) |
| 7 | RAG source citations in frontend | **In progress** | See [plan 04](docs/plans/04-rag-visible.md) |
| 8 | Production deployment | **Planned** | See [plan 08](docs/plans/08-deployment.md) |

---

## Getting Started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- 16 GB RAM minimum (32 GB recommended when running Ollama + Whisper together)
- GPU optional but strongly recommended for Ollama and Whisper speed
- A LiveAvatar account and API key (register at liveavatar.com — sandbox mode is free)

---

### Step 1 — Configure environment variables

```bash
# Windows (PowerShell)
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Open `.env` and set at minimum:
- `LIVEAVATAR_API_KEY` — your key from liveavatar.com
- `POSTGRES_PASSWORD` — any secure password
- `ADMIN_API_KEY` — any secret you'll use to call `/admin` endpoints

---

### Step 2 — Pull Ollama models

```bash
# Pull the LLM and embedding models (one-time, ~2-4 GB)
docker compose run --rm ollama ollama pull llama3.2
docker compose run --rm ollama ollama pull nomic-embed-text
```

### Step 3 — Download Kokoro TTS model files (first time only)

```bash
# Build the kokoro image first
docker compose build kokoro

# Download models into the persistent volume
docker compose run --rm kokoro python download_models.py
```

---

### Step 4 — Start all services

# Development (auto-uses override.yml with hot-reload + debug ports)
```bash
docker compose up -d
```

# Production (omit override.yml)
```bash
docker compose -f docker-compose.yml up -d
```

Wait ~30 seconds for all services to initialise. Check status with:

```bash
docker compose ps
docker compose logs -f backend
```

The database tables are created automatically on first backend startup (SQLAlchemy `create_all`).

---

---

### Step 5 — Verify everything is running

| Service | URL | Expected response |
|---|---|---|
| Backend API | http://localhost/api/health | `{"status":"ok"}` |
| API Docs (Swagger) | http://localhost/api/docs | Interactive API UI |
| Qdrant dashboard | http://localhost:6333/dashboard | Qdrant web UI |
| Ollama | http://localhost:11434 | `Ollama is running` |
| Kokoro TTS | http://localhost:8880/health | `{"status":"ok","model_loaded":true}` |

---

### Step 6 — Find your LiveAvatar avatar ID

Each professor needs a `avatar_id` — the UUID of a public avatar from LiveAvatar.

**Option A — Dashboard (recommended)**
1. Log in at [app.liveavatar.com](https://app.liveavatar.com/home)
2. Browse the **Avatars** section
3. Copy the UUID from any free/public avatar card

**Option B — API**
```bash
curl https://api.liveavatar.com/v1/avatars \
  -H "Authorization: Bearer your_api_key_here"
```
Each item in the response has an `id` field — that is the value to use.

**Option C — Known demo avatar (works immediately for testing)**
```
65f9e3c9-d48b-4118-b73a-4ae2e3cbb8f0
```
This UUID is the avatar shown in the official LiveAvatar quickstart and is confirmed public.

---

### Step 7 — Create your first professor (admin)

```bash
curl -X POST http://localhost/api/admin/professors \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: changeme" \
  -d '{
    "name": "Prof. García",
    "topic": "Calculus",
    "language": "both",
    "avatar_id": "65f9e3c9-d48b-4118-b73a-4ae2e3cbb8f0",
    "system_prompt": "You are Prof. García, a friendly and clear Calculus professor. Explain concepts step by step. Answer in the same language the student uses."
  }'
```

---

### Step 8 — Upload knowledge documents

```bash
curl -X POST http://localhost/api/admin/professors/{professor_id}/documents \
  -H "X-Admin-Key: changeme" \
  -F "file=@/path/to/calculus-notes.pdf"
```

Track ingestion status:

```bash
curl http://localhost/api/admin/professors/{professor_id}/documents \
  -H "X-Admin-Key: changeme"
```

Wait for `"status": "ready"` before starting a student session.

---

### Step 9 — Start a student session

```bash
# Register a student
curl -X POST http://localhost/api/sessions/students \
  -H "Content-Type: application/json" \
  -d '{"name": "Ana López", "email": "ana@school.edu", "language": "es"}'

# Open a session with a professor
curl -X POST http://localhost/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"student_id": "<student-id>", "professor_id": "<professor-id>"}'

# Send an audio question, receive audio answer (WAV)
curl -X POST http://localhost/api/sessions/{session_id}/speak \
  -F "audio=@question.wav" \
  --output answer.wav
```

---

### Stopping the stack

```bash
# Stop all services (data is preserved in volumes)
docker compose down

# Stop and remove all data volumes (full reset)
docker compose down -v
```

---

### GPU support (optional)

To enable GPU acceleration for Ollama and Whisper, uncomment the `deploy` block in `docker-compose.yml`:

```yaml
ollama:
  # ...
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu]
```

Requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) to be installed on the host.

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| Avatar & WebRTC | LiveAvatar LITE |
| Speech-to-Text | Whisper (local) |
| LLM | Ollama (llama3.2 / mistral) |
| Embeddings | Ollama nomic-embed-text |
| RAG Framework | LlamaIndex |
| Vector Database | Qdrant |
| Reranker | BGE cross-encoder (local) |
| Text-to-Speech | Kokoro TTS |
| Backend | FastAPI (Python) |
| Frontend | Next.js (TypeScript) |
| Relational DB | PostgreSQL 16 |
| Session Cache | Redis 7 |
| Observability | Langfuse (self-hosted) |
| Container | Docker Compose |
| Reverse Proxy | Nginx |
