# Virtual Professor

An AI-powered virtual professor system that lets students interact with avatar-based teachers via voice. Each professor is specialized in a specific topic and answers questions based on its own knowledge base. Built with LiveAvatar (LITE mode/mesh avatar), a Cloudflare Workers API, and a Next.js frontend deployed entirely on Cloudflare (Workers + D1 + Workers AI + AI Search).

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Data Models](#data-models)
- [Voice Interaction Flow](#voice-interaction-flow)
- [API Endpoints](#api-endpoints)
- [Directory Structure](#directory-structure)
- [Environment Variables](#environment-variables)
- [Getting Started](#getting-started)
- [Open Items](#open-items)

---

## Overview

- Admins create professors, each scoped to a specific topic (e.g., Mathematics, History, Biology)
- Admins upload knowledge documents (PDF, DOCX, PPTX, TXT, or web URLs)
- Students select a professor avatar and interact via voice in Spanish or English
- The browser captures speech (Web Speech API), the Worker retrieves relevant knowledge and replies with audio (Workers AI / Deepgram) that the speaking avatar renders
- If a student asks something outside the professor's topic, the system redirects them politely
- All conversation history and student sessions are persisted in Cloudflare D1

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         BROWSER (Student)                       │
│  ┌──────────────────┐        ┌──────────────────────────────┐   │
│  │  Student Portal  │        │   Speaking avatar / Avatar   │   │
│  │  (choose avatar) │        │   (TalkingHead / LiveAvatar) │   │
│  └────────┬─────────┘        └──────────┬───────────────────┘   │
└───────────┼──────────────────────────── │ ─────────────────────┘
            │ REST                        │ Audio
            ▼                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                 CLOUDFLARE WORKERS API  (Hono/TS)               │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │Session Router│  │ Admin Router │  │  Auth Router          │  │
│  │  /sessions/* │  │  /admin/*    │  │  /auth/* (JWT)        │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────┘  │
│         │                 │                                     │
│  ┌──────▼─────────────────▼──────────────────────────────────┐  │
│  │               Orchestrator (Agent)                         │  │
│  │   1. STT (browser) → 2. Scope Check → 3. RAG → 4. LLM     │  │
│  │         → 5. TTS (Workers AI / Deepgram)                  │  │
│  │  ┌────────────────────────────────────────────────────┐    │  │
│  │  │  Cloudflare D1 (professors, docs, sessions, msgs)  │    │  │
│  │  └────────────────────────────────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────┘│
└──────────────┼──────────────────┼─────────────────────────────┘
         │                  │
    ┌─────▼─────┐      ┌─────▼──────────┐      ┌──────────────┐
    │ Browser   │      │ Cloudflare     │      │ Cloudflare   │
    │ SpeechRec │      │ AI Search      │      │ Workers AI   │
    │ (STT only)│      │ (managed RAG)  │      │ (Deepgram    │
    │           │      │                │      │  TTS)        │
    └───────────┘      └────────────────┘      └──────────────┘
    ┌──────────────┐
    │ Google Gemini │ ← chat generation (OpenAI-compatible endpoint)
    └──────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     BROWSER (Admin)                             │
│   Admin Portal  →  Upload docs / manage professors / view logs  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Models

All relational data lives in Cloudflare D1 (SQLite). Tables: `users`, `refresh_tokens`, `students`, `professors`, `documents`, `sessions`, `messages`.

```
professors   id, name, topic, language (es|en|both), avatar_id,
             collection (Cloudflare folder prefix), system_prompt, created_at

documents    id, professor_id → professors, filename, format (pdf|docx|pptx|txt|url),
             status (pending|processing|ready|error), chunk_count, error_message, uploaded_at

students     id, name, email (UNIQUE), language (es|en), created_at

sessions     id, student_id → students, professor_id → professors,
             started_at, ended_at, credits_used

messages     id, session_id → sessions, role (student|professor),
             content, audio_path, sources_json, timestamp
```

---

## Voice Interaction Flow

```
1.  Student opens browser → selects professor avatar
2.  Avatar renderer initializes (TalkingHead / LiveAvatar)
3.  Student speaks → browser transcribes with Web Speech API (SpeechRecognition)
4.  Transcript (or typed fallback text) → POST /sessions/{id}/speak (JSON {"text": ...})
5.  D1: load last N messages (short-term memory / conversation context)
6.  Cloudflare AI Search: retrieve top-k chunks for that professor's folder
7.  Scope check (LLM): is the query related to the professor's topic?
    ├── IN SCOPE  → build prompt (system_prompt + history + retrieved context + query)
    │              → Gemini generates response text
    └── OUT OF SCOPE → static redirect: "Please ask questions related to [topic]."
8.  Response text → Workers AI Deepgram (aura-2) → audio/mpeg bytes
9.  Audio bytes returned to the frontend → avatar speaks + lip-syncs
10. Message pair (student + professor) saved to D1
```

**Short-term memory:** last 10 message pairs per session (configurable via `SESSION_MEMORY_MESSAGES`).
**Long-term memory:** full conversation history in D1, available for future sessions.

---

## API Endpoints

### Auth (`/auth`)
| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/register` | Register an admin user |
| `POST` | `/auth/login` | Login (JWT access + refresh tokens) |
| `POST` | `/auth/refresh` | Refresh access token |
| `GET` | `/auth/me` | Current user |

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
| `DELETE` | `/admin/documents/{id}` | Remove document and its Cloudflare index |
| `GET` | `/admin/documents/{id}/chunks` | Paginated stored chunks for a document |
| `POST` | `/admin/documents/{id}/reindex` | Re-index a document |
| `GET` | `/admin/indexing/status` | Per-professor indexing statistics |
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
| `POST` | `/sessions/{id}/local-avatar-connect` | Connect a local avatar for the session |
| `POST` | `/sessions/{id}/compress` | Compress completed session |
| `GET` | `/sessions/{id}/history` | Get conversation history |
| `GET` | `/sessions/{id}/messages/{id}/sources` | RAG source citations for a message |
| `DELETE` | `/sessions/{id}` | End session |

---

## Directory Structure

```
virtual-professor/
├── api/                             ← Cloudflare Workers API (Hono/TS)
│   ├── wrangler.toml                ← Worker config, vars, D1 binding
│   ├── migrations/                  ← D1 SQL migrations
│   ├── src/
│   │   ├── index.ts                 ← Hono app entry point (routes, CORS, rate limit)
│   │   ├── types.ts                 ← Env interface (vars, secrets, bindings)
│   │   ├── routes/                  ← auth, admin, professors, sessions, avatars, health
│   │   └── services/                ← llm.ts, rag.ts, tts.ts, ingest.ts
│   ├── test/                        ← Vitest integration tests (miniflare)
│   └── scripts/                     ← deploy helpers
│
├── services/
│   └── frontend/                    ← Next.js student + admin portal
│       ├── wrangler.jsonc           ← Cloudflare Workers deploy (open-next)
│       ├── vercel.json              ← optional Vercel deploy config
│       └── src/
│           ├── app/                 ← pages (session, admin, status)
│           ├── components/          ← student/ + admin/ + ui/
│           └── lib/                 ← api.ts (auth'd API client), auth.ts
│
├── openspec/                        ← SDD change specifications (OpenSpec)
├── .env.example                     ← reference for Cloudflare secrets/vars
└── README.md
```

---

## Environment Variables

The API reads configuration from `api/wrangler.toml` (`[vars]`) plus secrets set with `wrangler secret put`. See `.env.example` for the full reference list.

Key secrets (set as secrets):
- `GEMINI_API_KEY` — from [Google AI Studio](https://aistudio.google.com/app/apikey)
- `CLOUDFLARE_API_TOKEN` — token with AI Search:Edit/Run
- `CLOUDFLARE_ACCOUNT_ID` — owner account for AI Search
- `JWT_SECRET_KEY` — generate with `openssl rand -hex 32`
- `ADMIN_API_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` — default admin, seeded on first request

Key vars (in `wrangler.toml`):
- `GEMINI_LLM_MODEL=gemini-3.5-flash-lite` with fallback `GEMINI_FALLBACK_LLM_MODEL=gemini-3.5-flash`
- `CLOUDFLARE_AI_SEARCH_INSTANCE=virtual-professor`
- `TTS_MODEL_ES` / `TTS_MODEL_EN` = `@cf/deepgram/aura-2-es` / `@cf/deepgram/aura-2-en`
- `CORS_ORIGINS` — JSON array of allowed frontend origins

---

## Getting Started

### Prerequisites

- Node.js ≥ 20
- `wrangler` CLI (installed in `api/` and `services/frontend/`)
- A [Gemini API key](https://aistudio.google.com/app/apikey)
- A Cloudflare account with: Workers, D1, Workers AI, and an [AI Search](https://developers.cloudflare.com/ai-search/) instance + token (permissions **AI Search:Edit** and **AI Search:Run**)

### 1. Deploy the API

```bash
cd api
npm install
npx wrangler login
npx wrangler d1 migrations apply virtual-professor-db   # (or --remote)
npx wrangler secret put GEMINI_API_KEY
npx wrangler secret put CLOUDFLARE_API_TOKEN
npx wrangler secret put CLOUDFLARE_ACCOUNT_ID
npx wrangler secret put JWT_SECRET_KEY
npx wrangler secret put ADMIN_API_KEY
npx wrangler secret put ADMIN_EMAIL
npx wrangler secret put ADMIN_PASSWORD
npm run deploy    # wrangler deploy
```

Verify: `https://<worker>.workers.dev/health`

### 2. Deploy the frontend

```bash
cd services/frontend
npm install
npm run deploy    # opennextjs-cloudflare build + deploy
```

The frontend calls the API URL baked in at build time via `NEXT_PUBLIC_API_URL` (see `src/lib/api-base.ts`). Make sure the API's `CORS_ORIGINS` includes the frontend origin.

### 3. Create your first professor (admin)

Log in at the admin portal and create a professor, or use the API:

```bash
curl -X POST https://<api>/admin/professors \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Prof. García",
    "topic": "Calculus",
    "language": "both",
    "avatar_id": "<avatar-id>",
    "system_prompt": "You are Prof. García, a friendly and clear Calculus professor. Explain concepts step by step. Answer in the same language the student uses."
  }'
```

### 4. Upload knowledge documents

```bash
curl -X POST https://<api>/admin/professors/{professor_id}/documents \
  -H "Authorization: Bearer <admin-jwt>" \
  -F "file=@/path/to/calculus-notes.pdf"
```

Wait for document `"status": "ready"` (see `/admin/indexing/status`) before starting a student session. Cloudflare rejects files larger than **4 MB**.

### 5. Start a student session

```bash
# Register a student
curl -X POST https://<api>/sessions/students \
  -H "Content-Type: application/json" \
  -d '{"name": "Ana López", "email": "ana@school.edu", "language": "es"}'

# Open a session with a professor
curl -X POST https://<api>/sessions \
  -H "Content-Type: application/json" \
  -d '{"student_id": "<student-id>", "professor_id": "<professor-id>"}'

# Send a text question, receive an audio/mpeg answer
curl -X POST https://<api>/sessions/{session_id}/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "What is a derivative?"}' \
  --output answer.mp3
```

### Tests

```bash
cd api
npm test        # vitest + miniflare against the local D1 database
```

---

## Open Items

| # | Item | Status | Notes |
|---|---|---|---|
| 1 | LiveAvatar/TalkingHead avatar integration | Active | Avatar rendering in the frontend |
| 2 | LLM model selection | Done | Gemini `gemini-3.5-flash-lite` with `gemini-3.5-flash` fallback |
| 3 | TTS voice tuning | Done | Workers AI Deepgram aura-2 (ES/EN) |
| 4 | Cloudflare AI Search | Done | Managed RAG, files max 4 MB |
| 5 | Admin auth | Done | JWT-based, rate-limited |
| 6 | Student auth flow | Done | Session + JWT |
| 7 | RAG source citations in frontend | Done | `GET /sessions/{id}/messages/{id}/sources` |

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| Avatar rendering | TalkingHead / LiveAvatar (WebGL, browser-side) |
| Speech-to-Text | Browser Web Speech API (+ text fallback) |
| LLM | Google Gemini (`gemini-3.5-flash-lite` / fallback `gemini-3.5-flash`) |
| RAG | Cloudflare AI Search (Items + Search APIs) |
| Vector Database | Cloudflare (managed) |
| Text-to-Speech | Cloudflare Workers AI — Deepgram `aura-2` |
| API | Cloudflare Workers (Hono, TypeScript) |
| Database | Cloudflare D1 (SQLite) |
| Frontend | Next.js (TypeScript), deployed via OpenNext on Cloudflare Workers |
| Observability | Worker console logs / Cloudflare dashboard |