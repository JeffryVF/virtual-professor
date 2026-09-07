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
    │Whisper │  │  Z.AI  │  │    Qdrant    │ │ Kokoro  │
    │  STT   │  │  GLM   │  │  Vector DB   │ │   TTS   │
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

**Z.AI (GLM)**
- Cloud LLM via the [Z.AI Open Platform](https://docs.z.ai/guides/llm/glm-5) (OpenAI-compatible chat completions)
- Default model: `glm-4.7-flash` (free). Set `ZAI_LLM_MODEL=glm-5` to use GLM-5 (paid)
- Also provides `embedding-3` for RAG so no local Ollama process is required
- Thinking mode is disabled for short spoken professor replies

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
    │              → Z.AI GLM generates response text
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
Embedding: Z.AI embedding-3
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
├── render.yaml                       ← Render Blueprint (API + Postgres + Redis + Qdrant + Whisper + Kokoro)
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
│   │   │   ├── llm.py                ← Z.AI GLM client + prompt building
│   │   │   ├── embeddings.py         ← Z.AI embedding-3 client (RAG)
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
│   │   ├── vercel.json               ← Vercel project (Root Directory = services/frontend)
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

# Z.AI (GLM)
ZAI_API_KEY=your-z-ai-api-key
ZAI_BASE_URL=https://api.z.ai/api/paas/v4
ZAI_LLM_MODEL=glm-4.7-flash
ZAI_EMBED_MODEL=embedding-3

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
| 4 | GPU availability | Pending | Affects Whisper + Kokoro speed significantly |
| 5 | Admin auth | **In progress** | See [plan 02](docs/plans/02-auth-backend.md) |
| 6 | Student auth | **In progress** | See [plan 03](docs/plans/03-auth-frontend.md) |
| 7 | RAG source citations in frontend | **In progress** | See [plan 04](docs/plans/04-rag-visible.md) |
| 8 | Production deployment | **Planned** | See [plan 08](docs/plans/08-deployment.md) |

---

## Getting Started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- 8 GB RAM minimum (16 GB recommended when running Whisper + Kokoro locally)
- A [Z.AI](https://z.ai) API key (free `glm-4.7-flash` / `glm-4.5-flash` models are listed on [pricing](https://docs.z.ai/guides/overview/pricing))
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
- `LIVEAVATAR_API_KEY` — your key from liveavatar.com
- `POSTGRES_PASSWORD` — any secure password
- `ADMIN_API_KEY` — any secret you'll use to call `/admin` endpoints
- `JWT_SECRET_KEY` — generate with `openssl rand -hex 32`

---

### Step 2 — Download Kokoro TTS model files (first time only)

```bash
# Build the kokoro image first
docker compose build kokoro

# Download models into the persistent volume
docker compose run --rm kokoro python download_models.py
```

---

### Step 3 — Start all services

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

### Step 4 — Verify everything is running

| Service | URL | Expected response |
|---|---|---|
| Backend API | http://localhost/api/health | JSON with `"status": "healthy"` or `"degraded"` and a `zai` probe |
| API Docs (Swagger) | http://localhost/api/docs | Interactive API UI |
| Qdrant dashboard | http://localhost:6333/dashboard | Qdrant web UI |
| Kokoro TTS | http://localhost:8880/health | `{"status":"ok","model_loaded":true}` |

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

To enable GPU acceleration for Whisper, add an NVIDIA `deploy` reservation to the `whisper` service in `docker-compose.yml`. Requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) on the host. The LLM no longer runs locally.

---

## Cloud deployment (Vercel + Render)

Services are split so the LLM no longer eats RAM on the API box.

| Piece | Where | Config |
|---|---|---|
| Frontend | [Vercel](https://vercel.com) | Root Directory `services/frontend`. Env: `NEXT_PUBLIC_API_URL=https://<api>.onrender.com` |
| API | [Render](https://render.com) Blueprint `render.yaml` | `virtual-professor-api` — health `/health` |
| Postgres | Render | `virtual-professor-db` (private) |
| Redis | Render Key Value | `virtual-professor-redis` (private) |
| Qdrant | Render private service | `virtual-professor-qdrant` |
| Whisper STT | Render private service | `virtual-professor-whisper` (needs ~2 GB RAM) |
| Kokoro TTS | Render private service | `virtual-professor-kokoro` (downloads models on first boot) |

Do **not** proxy `/speak` or document uploads through Vercel — body limits are too small. The browser must call Render directly (`NEXT_PUBLIC_API_URL` = the API origin, no `/api` suffix).

### 1. Render (API + data + STT/TTS)

1. Push this branch to GitHub.
2. In Render: **New → Blueprint** → select the repo. Render reads [`render.yaml`](./render.yaml).
3. When prompted, set:
   - `ZAI_API_KEY` — from [z.ai](https://z.ai)
   - `CORS_ORIGINS` — `*` for the first boot, then your Vercel origin (`https://your-app.vercel.app`)
4. Wait until `virtual-professor-api` is Live. Copy its `https://….onrender.com` URL.
5. First Kokoro boot downloads ONNX voices onto the disk (several minutes).

### 2. Vercel (frontend)

1. **Add New Project** → this repo.
2. **Root Directory:** `services/frontend` (leave Framework as Next.js).
3. Environment variable:
   - `NEXT_PUBLIC_API_URL` = `https://virtual-professor-api.onrender.com` (no trailing slash, no `/api`)
4. Deploy. Copy the `https://….vercel.app` URL.

### 3. Lock CORS

Back on Render → `virtual-professor-api` → Environment:

```
CORS_ORIGINS=https://your-app.vercel.app
```

Redeploy the API (or wait for a Blueprint sync). Trailing slashes are stripped automatically.

### 4. Re-index knowledge

Embedding size is **1024** (`embedding-3`). Collections built with Ollama `nomic-embed-text` (768) will not search. Re-upload documents from the admin UI.

Default model is free `glm-4.7-flash`. Paid GLM-5: set `ZAI_LLM_MODEL=glm-5` on the API service.

### Local Docker still works

`docker compose up` keeps nginx + `NEXT_PUBLIC_API_URL=/api` + `ROOT_PATH=/api`. That path is only for the all-in-one compose stack, not for Vercel.

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| Avatar & WebRTC | LiveAvatar LITE |
| Speech-to-Text | Whisper (local) |
| LLM | Z.AI GLM (`glm-4.7-flash` free / `glm-5` paid) |
| Embeddings | Z.AI `embedding-3` |
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
