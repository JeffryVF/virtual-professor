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
- [ ] `docs/deployment.md` updated for any infrastructure changes

## Deployment

- [ ] `docker-compose.prod.yml` validated with `docker compose config`
- [ ] All services have healthchecks configured
- [ ] Resource limits (CPU/memory) set for all services
- [ ] `security_opt: ["no-new-privileges:true"]` present on all services
- [ ] No internal service exposes ports (only nginx has `ports:`)
- [ ] Nginx config validated: `docker compose exec nginx nginx -t`
- [ ] Backup strategy confirmed (Postgres + Qdrant)
- [ ] Backup script tested: `./scripts/backup.sh` runs without error
- [ ] SSL certificate valid (not expired)
- [ ] SSL auto-renewal cron job active: `crontab -l | grep certbot`
- [ ] `CORS_ORIGINS` is locked to production domain (not `*`)
- [ ] `JWT_SECRET_KEY` is a strong random value (not empty, not `changeme`)
- [ ] `LIVEAVATAR_API_KEY` set to production key (not placeholder)
- [ ] `LANGFUSE_ENABLE=true` set for observability
- [ ] Never `docker compose down -v` without explicit backup
- [ ] `client_max_body_size` is 55M (or correct for your use case)
- [ ] Rate limiting zones configured in `config/nginx.conf`

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
- [ ] Monitoring dashboards checked for anomalies
- [ ] SSL renewal tested: `certbot renew --dry-run`
