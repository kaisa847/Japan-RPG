#!/usr/bin/env bash
#
# Japan-RPG VPS Deployment Script
# Sets up the application with Docker, nginx reverse proxy, and Let's Encrypt SSL.
#
# Usage:
#   ./deploy.sh                   # interactive — prompts for domain and email
#   DOMAIN=example.com EMAIL=you@example.com ./deploy.sh   # non-interactive
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ─── Preflight checks ────────────────────────────────────────────────────────

if ! command -v docker &>/dev/null; then
    error "Docker is not installed. Install it first: https://docs.docker.com/engine/install/"
    exit 1
fi

if ! docker compose version &>/dev/null; then
    error "Docker Compose v2 is required. Update Docker or install the compose plugin."
    exit 1
fi

# ─── Gather configuration ────────────────────────────────────────────────────

if [[ -z "${DOMAIN:-}" ]]; then
    read -rp "Domain name (e.g. game.example.com): " DOMAIN
fi

if [[ -z "${EMAIL:-}" ]]; then
    read -rp "Email for Let's Encrypt notifications: " EMAIL
fi

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
    error "DOMAIN and EMAIL are required."
    exit 1
fi

info "Domain: $DOMAIN"
info "Email:  $EMAIL"

# ─── .env file ────────────────────────────────────────────────────────────────

if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        cp .env.example .env
        warn ".env created from .env.example — edit it to set ANTHROPIC_API_KEY before proceeding."
        warn "Then re-run this script."
        exit 1
    else
        error ".env file not found. Create one with at least ANTHROPIC_API_KEY=your_key"
        exit 1
    fi
fi

# Ensure DOMAIN is in .env
if ! grep -q "^DOMAIN=" .env; then
    echo "DOMAIN=$DOMAIN" >> .env
fi

# Ensure CORS_ORIGIN is in .env
if ! grep -q "^CORS_ORIGIN=" .env; then
    echo "CORS_ORIGIN=https://$DOMAIN" >> .env
fi

source .env

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    error "ANTHROPIC_API_KEY is not set in .env — the game needs it to function."
    exit 1
fi

# ─── Step 1: Start with HTTP-only nginx for certificate issuance ─────────────

info "Step 1/4 — Starting services with HTTP-only nginx..."
cp deploy/nginx/nginx-init.conf deploy/nginx/active.conf

docker compose up -d --build app nginx

info "Waiting for nginx to become ready..."
sleep 5

# ─── Step 2: Obtain Let's Encrypt certificate ───────────────────────────────

info "Step 2/4 — Requesting Let's Encrypt certificate for $DOMAIN..."

docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

# ─── Step 3: Switch to full SSL nginx config ─────────────────────────────────

info "Step 3/4 — Switching to SSL nginx configuration..."
cp deploy/nginx/nginx.conf deploy/nginx/active.conf

docker compose up -d --force-recreate nginx certbot

# ─── Step 4: Create admin user ───────────────────────────────────────────────

info "Step 4/4 — Setting up admin user..."
if docker compose exec app python -c "
from backend.auth import UserManager
um = UserManager(data_dir='/app/data')
users = um.list_users()
print(len(users))
" 2>/dev/null | grep -q "^0$"; then
    read -rsp "Choose admin password: " ADMIN_PW
    echo
    docker compose exec app python -m backend.create_user admin --admin <<< "$ADMIN_PW"
    info "Admin user 'admin' created."
else
    info "Users already exist — skipping admin creation."
fi

# ─── Set up automatic certificate renewal ────────────────────────────────────

CRON_CMD="0 3 * * * cd $SCRIPT_DIR && docker compose run --rm certbot renew --quiet && docker compose exec nginx nginx -s reload"
if ! crontab -l 2>/dev/null | grep -qF "certbot renew"; then
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    info "Cron job installed for automatic certificate renewal (daily 3:00 AM)."
else
    info "Certificate renewal cron job already exists."
fi

# ─── Done ─────────────────────────────────────────────────────────────────────

echo ""
info "=========================================="
info " Deployment complete!"
info "=========================================="
info ""
info " URL:   https://$DOMAIN"
info " Login: https://$DOMAIN/app/login.html"
info ""
info " Useful commands:"
info "   docker compose logs -f app     # Application logs"
info "   docker compose logs -f nginx   # Nginx logs"
info "   docker compose restart app     # Restart application"
info "   docker compose down            # Stop everything"
info "   docker compose up -d           # Start everything"
info ""
