# Virtual Professor — Deployment Guide

> Production deployment reference for the Virtual Professor AI tutor platform.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Docker | 24+ | `docker --version` |
| Docker Compose | 2.24+ | `docker compose version` |
| Git | 2.40+ | `git --version` |
| Domain | — | DNS A record pointing to your server IP |
| Server | Linux x86_64 | 16 GB RAM recommended, 4+ vCPUs |

### Recommended cloud specs

- **Minimum**: 4 vCPU, 16 GB RAM, 50 GB SSD
- **Recommended**: 8 vCPU, 32 GB RAM, 100 GB SSD
- **GPU optional**: Ollama benefits from GPU inference but runs on CPU

---

## 2. Server Setup

### 2.1 Install Docker

```bash
# Ubuntu / Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
newgrp docker

# Verify
docker --version
docker compose version
```

### 2.2 Firewall (UFW)

```bash
ufw allow 22/tcp       # SSH
ufw allow 80/tcp       # HTTP (certbot validation)
ufw allow 443/tcp      # HTTPS
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
ufw status verbose
```

### 2.3 System tuning

```bash
# Increase vm.max_map_count for Qdrant
echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Disable swap (optional, for performance)
sudo swapoff -a
```

---

## 3. Deployment Steps

### 3.1 Clone the repository

```bash
git clone https://github.com/your-org/virtual-professor.git
cd virtual-professor
```

### 3.2 Configure environment

```bash
cp .env.example .env
nano .env   # or vim
```

**Critical variables to set:**

| Variable | What to set |
|---|---|
| `DATABASE_URL` | `postgresql://user:pass@postgres:5432/virtual_profesor` |
| `JWT_SECRET_KEY` | `openssl rand -hex 32` output |
| `ADMIN_API_KEY` | `openssl rand -hex 32` output |
| `LIVEAVATAR_API_KEY` | Your LiveAvatar API key |
| `CORS_ORIGINS` | `https://your-domain.com` |
| `LANGFUSE_ENABLE` | `true` (recommended) |
| `LANGFUSE_SECRET_KEY` | Your Langfuse credentials |

### 3.3 Build and start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 3.4 Verify all services are running

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

# Health check
curl http://localhost:8000/health
# Expected: {"status":"ok", ...}
```

---

## 4. SSL Setup

### 4.1 Automated (recommended)

```bash
sudo ./scripts/setup-ssl.sh your-domain.com
```

This script:
- Installs Certbot if not present
- Obtains a Let's Encrypt certificate
- Configures automatic renewal via cron (daily at 3 AM)

### 4.2 Manual steps after SSL

After running the script, uncomment the HTTPS server block in `config/nginx.conf`
and reload nginx:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx
```

### 4.3 Verify SSL

```bash
curl -I https://your-domain.com
# Expected: HTTP/2 200
```

---

## 5. First Admin Setup

### 5.1 Run the seed script

The seed script runs **outside** Docker — it connects directly to the database.

```bash
# From the project root, if DATABASE_URL is set in .env:
export DATABASE_URL="postgresql://profesor:changeme@localhost:5432/virtual_profesor"
python scripts/seed-admin.py \
    --email admin@your-domain.com \
    --password "Str0ng!Pass" \
    --name "Admin User"
```

### 5.2 If the database is in Docker

If Postgres runs in a Docker container and is not exposed externally, run the
script from inside the network or expose the port temporarily:

```bash
# Option A: Run from host with port forwarding
# Add to docker-compose.prod.yml temporarily (remove after):
#   postgres:
#     ports: ["5432:5432"]
# Then restart and run seed-admin.py

# Option B: Copy and run inside the backend container
docker compose cp scripts/seed-admin.py backend:/tmp/
docker compose exec backend pip install bcrypt sqlalchemy psycopg2-binary
docker compose exec backend python /tmp/seed-admin.py \
    --email admin@your-domain.com --password "Str0ng!Pass" --name "Admin"
```

### 5.3 Verify the admin

```bash
# Login via API
curl -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@your-domain.com","password":"Str0ng!Pass"}'
# Expected: 200 with access_token and user.role="admin"
```

---

## 6. Backup Configuration

### 6.1 Manual backup

```bash
./scripts/backup.sh
```

This creates:
- `./backups/postgres_YYYYMMDD_HHMMSS.sql.gz` — PostgreSQL dump
- `./backups/qdrant_YYYYMMDD_HHMMSS/` — Qdrant collection snapshots

Backups older than 7 days are automatically cleaned up.

### 6.2 Cron job (recommended)

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /home/user/virtual-professor/scripts/backup.sh >> /home/user/virtual-professor/backups/backup.log 2>&1
```

### 6.3 Restore from backup

**PostgreSQL:**
```bash
gunzip -c ./backups/postgres_20250101_020000.sql.gz | \
    docker exec -i virtual-professor-postgres-1 psql -U profesor virtual_profesor
```

**Qdrant:**
```bash
# Upload snapshot file to Qdrant via API
curl -X POST \
    -H "Content-Type: multipart/form-data" \
    -F "snapshot=@./backups/qdrant_20250101_020000/my_collection_*.snapshot" \
    http://localhost:6333/collections/my_collection/snapshots/upload
```

---

## 7. Monitoring

### 7.1 Health endpoint

The backend exposes `/health` with per-service status:

```bash
curl http://localhost:8000/health
# {
#   "status": "ok",
#   "version": "0.1.0",
#   "services": {
#     "database": "ok",
#     "redis": "ok",
#     "qdrant": "ok",
#     "ollama": "ok",
#     "whisper": "ok",
#     "kokoro": "ok"
#   }
# }
```

### 7.2 Langfuse observability

When `LANGFUSE_ENABLE=true`, all LLM calls are traced in Langfuse:

- **Self-hosted**: `http://your-domain.com:3001` (port `3001`)
- **Cloud**: Your Langfuse cloud dashboard
- **What's traced**: LLM prompts/responses, latency, token usage, RAG chunks

### 7.3 Docker health checks

All services have health checks configured in `docker-compose.prod.yml`:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
# Every service should show "healthy" in the STATUS column
```

### 7.4 Logs

```bash
# Tail all services
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

# Tail a specific service
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend

# Last 100 lines with timestamps
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 -t backend
```

---

## 8. Troubleshooting

### 8.1 Service won't start

```bash
# Check logs for the failing service
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs <service>

# Common issues:
# - Postgres: Check POSTGRES_USER/POSTGRES_PASSWORD in .env
# - Qdrant: Verify vm.max_map_count is set (see §2.3)
# - Backend: Ensure DATABASE_URL is correct and reachable
# - Whisper: First run downloads the model (~1 GB), may time out
```

### 8.2 SSL certificate issues

```bash
# Check certificate expiry
certbot certificates

# Force renewal
certbot renew --force-renewal

# Test renewal process (no changes made)
certbot renew --dry-run
```

### 8.3 Out of disk space

```bash
# Check disk usage
df -h

# Prune Docker resources
docker system prune -af --volumes   # CAREFUL — removes all unused data

# Clean old backups manually
find ./backups -name "*.sql.gz" -mtime +7 -delete
find ./backups -type d -name "qdrant_*" -mtime +7 -exec rm -rf {} +
```

### 8.4 Cannot reach the API

```bash
# 1. Check nginx is running
docker compose ps nginx

# 2. Check nginx logs
docker compose logs nginx

# 3. Verify firewall
ufw status

# 4. Test backend directly (inside Docker network)
docker compose exec backend curl http://localhost:8000/health
```

---

## 9. Update Procedure

### 9.1 Standard update

```bash
# 1. Pull latest code
git pull origin main

# 2. Rebuild changed services
docker compose -f docker-compose.yml -f docker-compose.prod.yml build

# 3. Apply database migrations (if any)
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend \
    alembic upgrade head

# 4. Restart stack
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 9.2 Zero-downtime (frontend only)

If only the frontend changed:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps frontend
```

### 9.3 Verify after update

```bash
# Run the release checklist
# See RELEASE_CHECKLIST.md

# Quick smoke test
curl http://localhost:8000/health
curl -I https://your-domain.com
```

---

## 10. Rollback Procedure

### 10.1 Rollback to previous Docker images

```bash
# 1. Revert code
git checkout <previous-tag-or-commit>

# 2. Rebuild and restart
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 3. Revert database migrations (if needed)
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend \
    alembic downgrade -1
```

### 10.2 Restore database from backup

```bash
# 1. Stop the backend (to prevent writes during restore)
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop backend

# 2. Drop and recreate the database
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec postgres \
    psql -U profesor -c "DROP DATABASE virtual_profesor;"
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec postgres \
    psql -U profesor -c "CREATE DATABASE virtual_profesor;"

# 3. Restore
gunzip -c ./backups/postgres_<backup-date>.sql.gz | \
    docker exec -i virtual-professor-postgres-1 psql -U profesor virtual_profesor

# 4. Restart backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml start backend
```

### 10.3 Full stack rollback

```bash
# 1. Stop and remove containers (preserves volumes)
docker compose -f docker-compose.yml -f docker-compose.prod.yml down

# 2. Git checkout the previous release
git checkout <previous-release-tag>

# 3. Restore database (see §10.2)

# 4. Start fresh
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## Reference

| File | Purpose |
|---|---|
| `docker-compose.yml` | Base service definitions |
| `docker-compose.prod.yml` | Production overrides (limits, healthchecks, security) |
| `docker-compose.override.yml` | Development overrides (auto-applied, ignored in prod) |
| `config/nginx.conf` | Reverse proxy with rate limiting, caching, SSL |
| `.env` | Environment configuration (keep secure) |
| `scripts/backup.sh` | Automated PostgreSQL + Qdrant backup |
| `scripts/setup-ssl.sh` | Let's Encrypt SSL certificate setup |
| `scripts/seed-admin.py` | First admin user creation |
| `RELEASE_CHECKLIST.md` | Pre-release verification checklist |
