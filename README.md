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
- Admins upload knowledge documents (PDF, DOCX, PPTX, TXT, or web URLs)
- Students select a professor avatar and interact via voice in Spanish or English
- The browser captures speech (Web Speech API), the backend retrieves relevant knowledge and replies with audio (Edge-TTS) that the lip-synced avatar speaks
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
│  │   1. STT (browser) → 2. Scope Check → 3. RAG → 4. Reranker│  │
│  │         → 5. LLM Prompt → 6. TTS (Edge-TTS)               │  │
│  │                           ┌──────────────────────────┐     │  │
│  │                           │  Langfuse Observability   │     │  │
│  │                           │  (traces every step)      │     │  │
│  │                           └──────────────────────────┘     │  │
│  └──────┬───────────┬──────────────────┬──────────┬──────────┘  │
└─────────┼───────────┼──────────────────┼──────────┼────────────┘
          │           │                  │          │
    ┌─────┴────┐ ┌─────▼──┐  ┌───────────▼──┐ ┌────▼───────────┐
    │Browser   │ │  Z.AI  │  │ Qdrant Cloud │ │  Edge-TTS     │
    │SpeechRec │ │  GLM   │  │  (free tier) │ │  (Microsoft)  │
    │ognition  │ │        │  │  Vector DB   │ │   TTS         │
    └──────────┘ └────────┘  └──────┬───────┘ └────────────────┘
                                   │
                            ┌──────▼──────┐   ┌─────────┐
                            │ BGE Reranker│   │  Redis  │
                            │  (local)    │   │(sessions│
                            └─────────────┘   │ cache)  │
                                              └─────────┘
                            ┌──────────────┐
                            │  PostgreSQL  │
                            │  (Supabase:  │
                            │  profiles,   │
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
| `backend` | custom FastAPI | 8000 | Orchestrator, REST API, RAG, Edge-TTS, session management |
| `frontend` | custom Next.js | 3000 | Student portal + Admin portal (dev compose only; Render in prod) |
| `postgres` | `postgres:16` | 5432 | Relational data (professors, documents, sessions) |
| `redis` | `redis:7` | 6379 | Active session context cache |
| `nginx` | `nginx` | 80/443 | Reverse proxy (dev compose only) |
| Qdrant Cloud | managed free tier | 443/6333 | Per-professor vector collections |

### Service Responsibilities

**backend (FastAPI)**
- Receives text from the browser (Web Speech API transcript or typed text)
- Orchestrates the full pipeline: scope check → RAG → LLM → TTS
- Manages professors, documents, students, and sessions
- Runs document ingestion as background tasks
- Synthesizes speech with Edge-TTS and returns `audio/mpeg` bytes for the avatar

**Client-side Speech-to-Text**
- The browser captures audio and transcribes it with the **Web Speech API** (`SpeechRecognition`, Chrome/Edge)
- A visible text-input fallback covers Firefox/Safari where the API is unavailable
- No server-side STT service required

**Z.AI (GLM)**
- Cloud LLM via the [Z.AI Open Platform](https://docs.z.ai/guides/llm/glm-5) (OpenAI-compatible chat completions)
- Default model: `glm-4.7-flash` (free). Set `ZAI_LLM_MODEL=glm-5` to use GLM-5 (paid)
- RAG embeddings use Google Gemini `gemini-embedding-001` (768-d); set `GOOGLE_API_KEY`
- Thinking mode is disabled for short spoken professor replies

**Gemini (embeddings)**
- Cloud `gemini-embedding-001` (768-dim, Matryoshka; 1536/3072 also supported via `EMBED_DIM`)
- Queries use `RETRIEVAL_QUERY` and documents use `RETRIEVAL_DOCUMENT`
- Requires `GOOGLE_API_KEY` from [Google AI Studio](https://aistudio.google.com/apikey)

**Qdrant Cloud (free tier)**
- One collection per professor (`professors.collection`)
- Stores 768-dim Gemini vectors and chunk metadata (source filename, page label)
- Points are deleted and re-upserted on re-index
- Cluster URL + API key: [cloud.qdrant.io](https://cloud.qdrant.io)

**Edge-TTS**
- Converts LLM response text to `audio/mpeg` bytes via Microsoft's free neural voices
- ES/EN voices configured with `EDGE_TTS_VOICE_ES` / `EDGE_TTS_VOICE_EN`
- Returns audio bytes sent directly to LiveAvatar LITE for lip-sync

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
collection     VARCHAR     per-professor Qdrant collection name (uniq)
system_prompt  TEXT        personality and tone instructions for the LLM
created_at     TIMESTAMP
```

### documents
```
id             UUID        PRIMARY KEY
professor_id   UUID        FOREIGN KEY → professors.id
filename       VARCHAR     original filename
format         VARCHAR     pdf | docx | pptx | txt | url
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
sources_json   TEXT        JSON of RAG source citations
timestamp      TIMESTAMP
```

Chunk embeddings are **not** stored in PostgreSQL. Each professor has a Qdrant collection; points carry `document_id`, `source_filename`, `chunk_index`, and `page_label` in the payload.


---

## Voice Interaction Flow

```
1.  Student opens browser → selects professor avatar
2.  LiveAvatar Web SDK initializes WebRTC session (LITE mode)
3.  Student speaks → browser transcribes with Web Speech API (SpeechRecognition)
4.  Transcript (or typed fallback text) → POST /sessions/{id}/speak (JSON {"text": ...})
5.  Redis: load last N messages (short-term memory / conversation context)
6.  LlamaIndex: embed query → retrieve top-k chunks from Qdrant (cosine, per professor collection)
7.  Scope check (LLM): is the query related to the professor's topic?
    ├── IN SCOPE  → build prompt (system_prompt + history + retrieved context + query)
    │              → Z.AI GLM generates response text
    └── OUT OF SCOPE → static redirect: "Please ask questions related to [topic]."
8.  Response text → Edge-TTS → audio/mpeg bytes
9.  Audio bytes returned to LiveAvatar LITE → avatar lip-syncs and speaks
10. Message pair (student + professor) saved to PostgreSQL
11. Redis: update session context with new exchange
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
Format-specific reader (llama-index)
    ├── PDF  → PDFReader (+ PyMuPDF validation: encrypted / pages / scanned)
    ├── DOCX → DocxReader
    ├── PPTX → PptxReader
    ├── TXT  → plain text fallback
    └── URL  → SimpleWebPageReader(html_to_text=True)
    ↓
Text extraction + cleaning
    ↓
Chunking: 512 tokens, 50 token overlap, metadata tagging
    ↓
Embedding: Gemini gemini-embedding-001 (768-d, RETRIEVAL_DOCUMENT)
    ↓
Upsert points into the professor's Qdrant collection with source_filename metadata
    ↓
Document status updated to "ready"
```

**Continuous updates:** documents can be re-uploaded at any time. Old chunks are removed and replaced. The professor's data is always up to date.

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
| `POST` | `/admin/professors/{id}/documents` | Upload a knowledge document (pdf, docx, pptx, txt, url) |
| `GET` | `/admin/professors/{id}/documents` | List professor's documents |
| `GET` | `/admin/documents/{id}/chunks` | Paginated stored chunks for a document |
| `GET` | `/admin/indexing/status` | Per-professor indexing statistics |
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
| `POST` | `/sessions/{id}/speak` | Send text, receive `audio/mpeg` response bytes |
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
├── render.yaml                       ← Render Blueprint (API + Postgres + Redis)
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
│   │   │   ├── tts.py                ← Edge-TTS client (audio/mpeg)
│   │   │   ├── llm.py                ← Z.AI GLM client + prompt building
│   │   │   ├── embeddings.py         ← Gemini gemini-embedding-001 adapter
│   │   │   ├── rag.py                ← LlamaIndex + Qdrant retrieval
│   │   │   ├── reranker.py           ← BGE cross-encoder reranker
│   │   │   ├── memory.py             ← Redis session context manager
│   │   │   ├── ingestion.py          ← document processing pipeline
│   │   │   ├── qdrant_store.py       ← Qdrant collections and point filters
│   │   │   ├── liveavatar.py         ← LiveAvatar LITE connector
│   │   │   └── langfuse.py           ← Langfuse observability helpers
│   │   ├── models/
│   │   │   ├── db.py                 ← SQLAlchemy ORM models
│   │   │   └── schemas.py            ← Pydantic request/response schemas
│   │   ├── core/
│   │   │   ├── config.py             ← settings from environment variables
│   │   │   ├── qdrant.py             ← Qdrant Cloud client factory
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
│   │   ├── Dockerfile.prod            ← Render build (standalone Next.js)
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
├── data/
│   ├── uploads/                      ← raw uploaded files (mounted volume)
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

The stack is defined in [`docker-compose.yml`](./docker-compose.yml) at the repo root. It includes 6 services:

| Service | Image | Role |
|---------|-------|------|
| `nginx` | nginx:alpine | Reverse proxy (dev just for convenience) |
| `frontend` | custom Node.js | Next.js app. Real prod hosting is Render (`Dockerfile.prod`) |
| `backend` | custom Python | FastAPI orchestrator |
| `postgres` | postgres:16 | Relational DB (Supabase in prod) |
| `redis` | redis:7-alpine | Session cache |

Development overrides (hot-reload, debug ports) live in `docker-compose.override.yml` and are applied automatically when you run `docker compose up`.

> ⚠️ The inline YAML previously shown here was always stale — see the actual [`docker-compose.yml`](./docker-compose.yml) for the source of truth.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values.

```env
# PostgreSQL (relational; Supabase in production)
POSTGRES_USER=profesor
POSTGRES_PASSWORD=changeme
POSTGRES_DB=virtual_profesor
DATABASE_URL=postgresql://profesor:changeme@postgres:5432/virtual_profesor

# Redis
REDIS_URL=redis://redis:6379

# Qdrant Cloud free tier — https://cloud.qdrant.io
QDRANT_URL=https://xxxx.us-east-1-0.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=your-qdrant-api-key

# Z.AI (GLM — chat LLM only; international API has no embedding models)
ZAI_API_KEY=your-z-ai-api-key
ZAI_BASE_URL=https://api.z.ai/api/paas/v4
ZAI_LLM_MODEL=glm-4.7-flash

# Embeddings (RAG). Gemini gemini-embedding-001.
GOOGLE_API_KEY=your-google-api-key
EMBED_PROVIDER=gemini
EMBED_MODEL=gemini-embedding-001
EMBED_DIM=768

# Edge-TTS
EDGE_TTS_VOICE_EN=en-US-JennyNeural
EDGE_TTS_VOICE_ES=es-ES-ElviraNeural
EDGE_TTS_RATE=+0%
TTS_MAX_TOTAL_CHARS=6000

# LiveAvatar
LIVEAVATAR_API_KEY=your_key_here
LIVEAVATAR_API_URL=https://api.liveavatar.com

# Admin
ADMIN_API_KEY=changeme

# Default admin user — seeded automatically on first startup.
# Set a real password before deploying anywhere public.
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=changeme
ADMIN_NAME=Administrator

# Session memory
SESSION_MEMORY_MESSAGES=10
SESSION_TIMEOUT_MINUTES=30
```

---

## Open Items

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | LiveAvatar API key + sandbox | Pending | Register at liveavatar.com to get key and test LITE mode |
| 2 | LLM model selection | Pending | Start with free `glm-4.7-flash` or paid `glm-5` |
| 3 | Edge-TTS voice tuning | Done | ES/EN voices via `EDGE_TTS_VOICE_ES` / `EDGE_TTS_VOICE_EN` |
| 4 | Embedding size lock | Done | Qdrant collections are `size=768` (`gemini-embedding-001`) |
| 5 | Admin auth | **In progress** | See [plan 02](docs/plans/02-auth-backend.md) |
| 6 | Student auth | **In progress** | See [plan 03](docs/plans/03-auth-frontend.md) |
| 7 | RAG source citations in frontend | **In progress** | See [plan 04](docs/plans/04-rag-visible.md) |
| 8 | Production deployment | **Planned** | See [plan 08](docs/plans/08-deployment.md) |

---

## Getting Started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- A [Z.AI](https://z.ai) API key (free `glm-4.7-flash` / `glm-4.5-flash` models are listed on [pricing](https://docs.z.ai/guides/overview/pricing))
- A [Google AI Studio](https://aistudio.google.com/apikey) API key for `gemini-embedding-001`
- A [Qdrant Cloud](https://cloud.qdrant.io) free-tier cluster (URL + API key)
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
- `ZAI_API_KEY` — your key from [z.ai](https://z.ai)
- `GOOGLE_API_KEY` — Gemini embeddings from [Google AI Studio](https://aistudio.google.com/apikey)
- `QDRANT_URL` / `QDRANT_API_KEY` — free cluster at [cloud.qdrant.io](https://cloud.qdrant.io)
  (must be `https://….cloud.qdrant.io:6333`; example placeholders prevent the API from starting)
- `LIVEAVATAR_API_KEY` — your key from liveavatar.com
- `POSTGRES_PASSWORD` — any secure password
- `ADMIN_API_KEY` — any secret you'll use to call `/admin` endpoints
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — the default admin login seeded on first startup
- `JWT_SECRET_KEY` — generate with `openssl rand -hex 32`

---

### Step 2 — Start all services

# Development (auto-uses override.yml with hot-reload + debug ports)
```bash
docker compose up -d
```

# Production (omit override.yml)
```bash
docker compose -f docker-compose.yml up -d
```

Qdrant Cloud is **not** a Compose service. The backend talks to your free-tier cluster
using `QDRANT_URL` and `QDRANT_API_KEY`. Postgres in Compose stores relational data only.

Wait ~30 seconds for all services to initialise. Check status with:

```bash
docker compose ps
docker compose logs -f backend
```

The database tables are created automatically on first backend startup (SQLAlchemy `create_all`).

---

### Step 4 — Verify everything is running

| Service | URL | Expected response |
|---|---|---|
| Backend API | http://localhost/api/health | JSON with `"status": "healthy"` or `"degraded"` and `postgres`/`redis`/`zai`/`qdrant`/`gemini` probes |
| API Docs (Swagger) | http://localhost/api/docs | Interactive API UI |

---

### Step 5 — Find your LiveAvatar avatar ID

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

### Step 6 — Create your first professor (admin)

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

### Step 7 — Upload knowledge documents

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

### Step 8 — Start a student session

```bash
# Register a student
curl -X POST http://localhost/api/sessions/students \
  -H "Content-Type: application/json" \
  -d '{"name": "Ana López", "email": "ana@school.edu", "language": "es"}'

# Open a session with a professor
curl -X POST http://localhost/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"student_id": "<student-id>", "professor_id": "<professor-id>"}'

# Send a text question, receive an audio/mpeg answer
curl -X POST http://localhost/api/sessions/{session_id}/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "What is a derivative?"}' \
  --output answer.mp3
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

## Cloud deployment (Render only)

Render hosts the frontend, API, and a volatile Redis cache. Supabase hosts
persistent PostgreSQL (relational data only). Qdrant Cloud free tier hosts
the vector collections.

| Piece | Where | Config |
|---|---|---|
| Frontend | Render Blueprint | `virtual-professor-frontend` — Next.js standalone, health `/` |
| API | Render Blueprint | `virtual-professor-api` — health `/health` |
| Postgres | Supabase | Project database connection string |
| Vectors | Qdrant Cloud (free) | Cluster URL + API key |
| Redis | Render Key Value | `virtual-professor-redis` (private) |

The browser calls the Render API directly (`NEXT_PUBLIC_API_URL` is baked into the frontend at **build time** via a Docker build arg pointing at the API origin). Do **not** proxy `/speak` or document uploads through the frontend — keep them hitting the API origin directly.

### 1. Deploy the blueprint

1. Create a [Qdrant Cloud](https://cloud.qdrant.io) cluster on the **free tier**. Copy the
   cluster URL (`https://….cloud.qdrant.io:6333`) and an API key.
2. Create a Supabase project. Copy its **Session pooler** connection string and
   convert it to `postgresql+asyncpg://` for `DATABASE_URL`. The `vector`
   extension is no longer required.
3. Push this branch to GitHub.
4. In Render: **New → Blueprint** → select the repo. Render reads
   [`render.yaml`](./render.yaml).
5. Set `DATABASE_URL`, `ZAI_API_KEY`, `GOOGLE_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`,
   `ADMIN_EMAIL`, and `ADMIN_PASSWORD` in the API service environment.
6. Wait until `virtual-professor-api` and
   `virtual-professor-frontend` are Live.
   - API: `https://virtual-professor-api.onrender.com/health` (includes a `qdrant` probe)
   - Frontend: `https://virtual-professor-frontend.onrender.com/`

### 2. CORS

`render.yaml` pre-sets `CORS_ORIGINS=https://virtual-professor-frontend.onrender.com` on the API. If you rename the frontend service, update its `.onrender.com` origin and redeploy the API.

### 3. Vectorize knowledge

The API creates relational tables on boot. Embeddings are upserted into
Qdrant Cloud (`VECTOR` size 768, cosine) **on upload**, not at startup.
Keep `RERANKER_TYPE=none` on Render Free so the BGE cross-encoder is not
loaded into the 512MB instance.

If a document stays on `pending` or `error` after upload, check
`GOOGLE_API_KEY` and Qdrant, then re-index from the admin UI.

Render Free services have ephemeral filesystems, so uploaded source files are
lost on restart. Indexed chunks remain in Qdrant Cloud. If a document shows
`SOURCE_MISSING`, re-upload it from the admin UI.

Default model is free `glm-4.7-flash`. Paid GLM-5: set `ZAI_LLM_MODEL=glm-5` on the API service.

### Local Docker still works

`docker compose up` keeps nginx + `NEXT_PUBLIC_API_URL=/api` + `ROOT_PATH=/api`. That path is only for the all-in-one compose stack, not for Render.

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| Avatar & WebRTC | LiveAvatar LITE |
| Speech-to-Text | Browser Web Speech API (+ text fallback) |
| LLM | Z.AI GLM (`glm-4.7-flash` free / `glm-5` paid) |
| Embeddings | Gemini `gemini-embedding-001` (768 dims) |
| RAG Framework | LlamaIndex |
| Vector Database | Qdrant Cloud (free tier) |
| Reranker | BGE cross-encoder (local) |
| Text-to-Speech | Edge-TTS (Microsoft neural voices) |
| Backend | FastAPI (Python) |
| Frontend | Next.js (TypeScript) |
| Relational DB | PostgreSQL 16 (Supabase) |
| Session Cache | Redis 7 |
| Observability | Langfuse (self-hosted) |
| Container | Docker Compose |
| Reverse Proxy | Nginx |
