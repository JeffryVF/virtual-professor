# Release Checklist — Virtual Professor

> Use this checklist before every production release. Each item must be verified or explicitly marked N/A.

---

## Pre-Release

- [ ] CHANGELOG is updated with all changes since last release
- [ ] Version bumped in `services/backend/main.py` (if applicable)
- [ ] Version bumped in `services/frontend/package.json`
- [ ] All environment variables are documented in `.env.example`
- [ ] No `TODO`, `FIXME`, or `DEBUG` code committed
- [ ] Git tag created for the release (`v{X}.{Y}.{Z}`)

## Auth & Security

- [ ] Admin endpoints use JWT authentication (not `X-Admin-Key`)
- [ ] Student endpoints require authentication where appropriate
- [ ] All passwords hashed with bcrypt (not plaintext)
- [ ] `NEXT_PUBLIC_ADMIN_KEY` removed from frontend
- [ ] CORS origins locked to specific domains (not `*`)
- [ ] Rate limiting enabled on auth endpoints
- [ ] Security headers applied (CSP, HSTS, X-Content-Type-Options)
- [ ] No default/fallback secrets (`changeme`, `your_key_here`, etc.)
- [ ] Logs do not contain passwords, tokens, or secrets

## Tests

- [ ] `cd services/backend && pytest` — all tests pass
- [ ] Backend test coverage ≥ 80%
- [ ] `cd services/frontend && npm test` — all tests pass
- [ ] `cd services/frontend && npm run build` — compiles without errors

## Documentation

- [ ] `README.md` reflects current project state
- [ ] `.env.example` has all required variables with descriptions
- [ ] API changes documented in README endpoint table
- [ ] Troubleshooting guide updated if RAG pipeline changed

## Deployment

- [ ] `docker-compose.prod.yml` validated (or production compose config)
- [ ] All services have healthchecks configured
- [ ] Resource limits (CPU/memory) set for all services
- [ ] Backup strategy confirmed (Postgres + Qdrant)
- [ ] Never `docker compose down -v` without explicit backup

## Smoke Test

- [ ] `docker compose up -d` starts all services (`docker compose ps` shows all up)
- [ ] Health endpoint returns `{"status":"ok"}` with all services green
- [ ] Admin can create a professor
- [ ] Admin can upload a document
- [ ] Document indexing completes (status: `ready`)
- [ ] Student can register and start a session
- [ ] Speak endpoint returns audio response
- [ ] Conversation history is persisted and retrievable

## Post-Release

- [ ] Release tag pushed to remote
- [ ] Production environment updated
- [ ] Langfuse traces verified for a test session
- [ ] Backup of pre-release state confirmed
