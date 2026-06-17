#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# setup-ssl.sh — Obtain and auto-renew SSL certificates via Certbot
# ═══════════════════════════════════════════════════════════════
# Usage:
#   chmod +x scripts/setup-ssl.sh
#   sudo ./scripts/setup-ssl.sh your-domain.com
#
# Prerequisites:
#   - Docker Compose stack is running (nginx exposes ports 80 and 443)
#   - DNS A record points to this server's public IP
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# ── Color helpers ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Argument check ──────────────────────────────────────────────────────────
if [ $# -lt 1 ]; then
    error "Usage: $0 <your-domain.com>"
    echo ""
    echo "Example:"
    echo "  sudo $0 app.virtualprofessor.com"
    exit 1
fi

DOMAIN="$1"
COMPOSE_PROJECT="virtual-professor"

# ── Pre-flight checks ──────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    error "This script must be run as root (sudo). Certbot needs port 80 access."
    exit 1
fi

info "Domain: $DOMAIN"

# ── 1. Install Certbot if not present ──────────────────────────────────────
if ! command -v certbot &>/dev/null; then
    info "Certbot not found. Installing..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq && apt-get install -y -qq certbot python3-certbot-nginx
    elif command -v yum &>/dev/null; then
        yum install -y epel-release && yum install -y certbot python3-certbot-nginx
    elif command -v dnf &>/dev/null; then
        dnf install -y certbot python3-certbot-nginx
    elif command -v apk &>/dev/null; then
        apk add --no-cache certbot certbot-nginx
    else
        error "Package manager not recognized. Install certbot manually:"
        error "  https://certbot.eff.org/instructions"
        exit 1
    fi
    info "Certbot installed."
else
    info "Certbot already installed."
fi

# ── 2. Run Certbot ──────────────────────────────────────────────────────────
info "Obtaining SSL certificate for $DOMAIN ..."
certbot --nginx \
    --domain "$DOMAIN" \
    --non-interactive \
    --agree-tos \
    --email "admin@${DOMAIN}" \
    --redirect

if [ $? -ne 0 ]; then
    error "Certbot failed. Check that:"
    error "  - DNS A record for $DOMAIN points to this server's public IP"
    error "  - Port 80 is reachable (not blocked by firewall)"
    error "  - The Docker Compose nginx is running and listening on port 80"
    error ""
    error "Run manually: certbot --nginx -d $DOMAIN"
    exit 1
fi

info "SSL certificate obtained successfully for $DOMAIN"

# ── 3. Auto-renewal cron job ───────────────────────────────────────────────
CERTBOT_CRON="0 3 * * * /usr/bin/certbot renew --quiet --no-self-upgrade && docker compose -p ${COMPOSE_PROJECT} exec nginx nginx -s reload"

# Check if the cron job already exists
EXISTING_CRON=$(crontab -l 2>/dev/null || true)
if echo "$EXISTING_CRON" | grep -q "certbot renew"; then
    info "Certbot auto-renewal cron job already exists. Skipping."
else
    (echo "$EXISTING_CRON" ; echo "$CERTBOT_CRON") | crontab -
    info "Auto-renewal cron job installed:"
    info "  $CERTBOT_CRON"
fi

# ── 4. Next steps ───────────────────────────────────────────────────────────
info "✅ SSL setup complete for $DOMAIN"
echo ""
echo "Next steps:"
echo "  1. Uncomment the HTTPS server block in config/nginx.conf"
echo "     and replace 'your-domain.com' with $DOMAIN"
echo "  2. Restart nginx: docker compose -p ${COMPOSE_PROJECT} restart nginx"
echo "  3. Verify: curl -I https://$DOMAIN"
echo "  4. Test renewal: certbot renew --dry-run"
