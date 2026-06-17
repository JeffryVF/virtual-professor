#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# backup.sh — Automated backup for PostgreSQL + Qdrant
# ═══════════════════════════════════════════════════════════════
# Usage:
#   chmod +x scripts/backup.sh
#   ./scripts/backup.sh                    # uses defaults
#   ./scripts/backup.sh --dir /custom/path # custom backup directory
#
# Requires:
#   - Docker Compose project running (or --no-docker for direct pg_dump)
#   - pg_dump available inside the postgres container
#   - Qdrant HTTP API accessible at the configured QDRANT_URL
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
BACKUP_DIR="$(cd "$(dirname "$0")/.." && pwd)/backups"
RETENTION_DAYS=7
LOG_FILE="${BACKUP_DIR}/backup.log"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
COMPOSE_PROJECT="virtual-professor"

# Source .env for DB credentials
ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"

# Color helpers
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*" | tee -a "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*" | tee -a "$LOG_FILE"; }
error() { echo -e "${RED}[ERROR]${NC} $*" | tee -a "$LOG_FILE" >&2; }

# ── Parse options ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)
            BACKUP_DIR="$2"
            LOG_FILE="${BACKUP_DIR}/backup.log"
            shift 2
            ;;
        *)
            error "Unknown option: $1"
            echo "Usage: $0 [--dir /path/to/backup]"
            exit 1
            ;;
    esac
done

# ── Source .env ─────────────────────────────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
else
    warn ".env file not found at $ENV_FILE — relying on environment variables"
fi

# ── Ensure backup directory exists ──────────────────────────────────────────
mkdir -p "$BACKUP_DIR"
touch "$LOG_FILE"

info "═══ Backup started: $TIMESTAMP ═══"
info "Backup directory: $BACKUP_DIR"
info "Retention: $RETENTION_DAYS days"

# ── 1. PostgreSQL backup via pg_dump ────────────────────────────────────────
PG_CONTAINER="${COMPOSE_PROJECT}-postgres-1"
PG_USER="${POSTGRES_USER:-profesor}"
PG_DB="${POSTGRES_DB:-virtual_profesor}"
PG_DUMP_FILE="${BACKUP_DIR}/postgres_${TIMESTAMP}.sql.gz"

info "Dumping PostgreSQL database '$PG_DB'..."

if docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" "$PG_DB" 2>/dev/null | gzip > "$PG_DUMP_FILE"; then
    PG_SIZE=$(du -h "$PG_DUMP_FILE" | cut -f1)
    info "  ✅ PostgreSQL backup saved: $PG_DUMP_FILE ($PG_SIZE)"
else
    error "  ❌ PostgreSQL backup FAILED"
    error "     Check that container '$PG_CONTAINER' is running"
    error "     and pg_dump is available inside it."
fi

# ── 2. Qdrant snapshot ──────────────────────────────────────────────────────
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
QDRANT_SNAPSHOT_DIR="${BACKUP_DIR}/qdrant_${TIMESTAMP}"
mkdir -p "$QDRANT_SNAPSHOT_DIR"

info "Requesting Qdrant full snapshot..."

# Get list of collections first
COLLECTIONS_JSON=$(curl -s "${QDRANT_URL}/collections" 2>/dev/null || echo '{"result": {"collections": []}}')
COLLECTION_NAMES=$(echo "$COLLECTIONS_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    cols = data.get('result', {}).get('collections', [])
    for c in cols:
        print(c.get('name', ''))
except Exception:
    pass
" 2>/dev/null || true)

if [ -z "$COLLECTION_NAMES" ]; then
    warn "  No Qdrant collections found or unable to reach Qdrant at $QDRANT_URL"
    warn "  Check that the Qdrant container is running and QDRANT_URL is correct."
else
    for COLLECTION in $COLLECTION_NAMES; do
        info "  Snapshotting collection: $COLLECTION"
        SNAPSHOT_RESULT=$(curl -s -X POST "${QDRANT_URL}/collections/${COLLECTION}/snapshots" 2>/dev/null || echo '{"error": "request failed"}')

        SNAPSHOT_NAME=$(echo "$SNAPSHOT_RESULT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('result', {}).get('name', ''))
except Exception:
    pass
" 2>/dev/null || true)

        if [ -n "$SNAPSHOT_NAME" ]; then
            # Download the snapshot
            curl -s -o "${QDRANT_SNAPSHOT_DIR}/${COLLECTION}_${SNAPSHOT_NAME}" \
                "${QDRANT_URL}/collections/${COLLECTION}/snapshots/${SNAPSHOT_NAME}" \
                2>/dev/null && \
            info "    ✅ Snapshot saved: ${COLLECTION}_${SNAPSHOT_NAME}" || \
            warn "    ⚠️  Could not download snapshot for '$COLLECTION'"
        else
            warn "    ⚠️  Snapshot creation failed for '$COLLECTION': $SNAPSHOT_RESULT"
        fi
    done
    QDRANT_SIZE=$(du -sh "$QDRANT_SNAPSHOT_DIR" 2>/dev/null | cut -f1 || echo "0B")
    info "  ✅ Qdrant snapshots saved to: $QDRANT_SNAPSHOT_DIR ($QDRANT_SIZE)"
fi

# ── 3. Cleanup old backups (7-day retention) ────────────────────────────────
info "Cleaning up backups older than $RETENTION_DAYS days..."

DELETED_COUNT=0
while IFS= read -r -d '' OLD_FILE; do
    rm -f "$OLD_FILE"
    DELETED_COUNT=$((DELETED_COUNT + 1))
done < <(find "$BACKUP_DIR" -name "postgres_*.sql.gz" -mtime +"${RETENTION_DAYS}" -print0 2>/dev/null)

while IFS= read -r -d '' OLD_DIR; do
    if [ -d "$OLD_DIR" ]; then
        rm -rf "$OLD_DIR"
        DELETED_COUNT=$((DELETED_COUNT + 1))
    fi
done < <(find "$BACKUP_DIR" -maxdepth 1 -name "qdrant_*" -type d -mtime +"${RETENTION_DAYS}" -print0 2>/dev/null)

if [ "$DELETED_COUNT" -gt 0 ]; then
    info "  Cleaned up $DELETED_COUNT old backup(s)"
else
    info "  No old backups to clean up"
fi

# ── 4. Summary ──────────────────────────────────────────────────────────────
info "═══ Backup completed: $(date +%Y%m%d_%H%M%S) ═══"
info ""
info "Summary:"
info "  PostgreSQL: ${PG_DUMP_FILE:-FAILED}"
info "  Qdrant:     ${QDRANT_SNAPSHOT_DIR:-SKIPPED}"
info ""
info "To restore PostgreSQL:"
info "  gunzip -c ${PG_DUMP_FILE:-<backup-file>} | docker exec -i ${COMPOSE_PROJECT}-postgres-1 psql -U $PG_USER $PG_DB"
info ""
info "To restore Qdrant:"
info "  Upload snapshot via Qdrant API or copy to the Qdrant storage volume"
