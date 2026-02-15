#!/usr/bin/env bash
#
# Japan-RPG VPS Deployment Script
# Natives Setup mit systemd, nginx und Let's Encrypt (ohne Docker).
#
# Usage:
#   sudo ./deploy.sh                                          # interactive
#   sudo DOMAIN=game.example.com EMAIL=me@mail.com ./deploy.sh  # non-interactive
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/home/jrpg"
SERVICE_USER="jrpg"

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ─── Root check ──────────────────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (sudo ./deploy.sh)"
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

# ─── Step 1: Install system packages ─────────────────────────────────────────

info "Step 1/7 — Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx certbot python3-certbot-nginx

# ─── Step 2: Create service user ─────────────────────────────────────────────

info "Step 2/7 — Setting up service user and directories..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --create-home --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
    info "User '$SERVICE_USER' created with home $INSTALL_DIR."
fi

# ─── Step 3: Install application ─────────────────────────────────────────────

info "Step 3/7 — Installing application to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# Copy project files (exclude deploy artifacts, git, etc.)
rsync -a --delete \
    --exclude='.git' \
    --exclude='.env' \
    --exclude='data/users/' \
    --exclude='data/users.json' \
    --exclude='data/.jwt_secret' \
    --exclude='data/saves/' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='assets/' \
    "$SCRIPT_DIR/" "$INSTALL_DIR/"

# Create Python venv & install dependencies
if [[ ! -d "$INSTALL_DIR/venv" ]]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/backend/requirements.txt" gunicorn

# Generate placeholder assets if missing
if [[ ! -d "$INSTALL_DIR/assets/characters" ]]; then
    info "Generating placeholder assets..."
    cd "$INSTALL_DIR"
    "$INSTALL_DIR/venv/bin/python" generate_placeholders.py
fi

# Ensure data directories exist
mkdir -p "$INSTALL_DIR/data/users" "$INSTALL_DIR/data/saves"

# ─── Step 4: .env file ──────────────────────────────────────────────────────

info "Step 4/7 — Configuring environment..."
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    if [[ -f "$SCRIPT_DIR/.env" ]]; then
        cp "$SCRIPT_DIR/.env" "$INSTALL_DIR/.env"
    elif [[ -f "$INSTALL_DIR/.env.example" ]]; then
        cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
        warn ".env created from template — edit $INSTALL_DIR/.env to set ANTHROPIC_API_KEY, then re-run."
        exit 1
    else
        error "No .env file found. Create $INSTALL_DIR/.env with at least ANTHROPIC_API_KEY=your_key"
        exit 1
    fi
fi

# Ensure CORS_ORIGIN is set
if ! grep -q "^CORS_ORIGIN=" "$INSTALL_DIR/.env"; then
    echo "CORS_ORIGIN=https://$DOMAIN" >> "$INSTALL_DIR/.env"
fi

# Validate API key
set -a; source "$INSTALL_DIR/.env"; set +a
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    error "ANTHROPIC_API_KEY is not set in $INSTALL_DIR/.env"
    exit 1
fi

# Set ownership
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ─── Step 5: Install systemd service ─────────────────────────────────────────

info "Step 5/7 — Installing systemd service..."
cp "$INSTALL_DIR/deploy/japan-rpg.service" /etc/systemd/system/japan-rpg.service
systemctl daemon-reload
systemctl enable japan-rpg
systemctl restart japan-rpg

info "Waiting for application to start..."
sleep 3

if systemctl is-active --quiet japan-rpg; then
    info "Application is running."
else
    error "Application failed to start. Check: journalctl -u japan-rpg"
    exit 1
fi

# ─── Step 6: Configure nginx + Let's Encrypt ─────────────────────────────────

info "Step 6/7 — Configuring nginx and SSL certificate..."

# Install nginx config with domain placeholder replaced
sed "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" \
    "$INSTALL_DIR/deploy/nginx/japan-rpg.conf" \
    > /etc/nginx/sites-available/japan-rpg

# Disable default site, enable ours
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/japan-rpg /etc/nginx/sites-enabled/japan-rpg

# Create certbot webroot
mkdir -p /var/www/certbot

# First: test with HTTP-only (comment out SSL block temporarily)
# Use a minimal config that just serves the ACME challenge
cat > /etc/nginx/sites-available/japan-rpg-init <<'INITCONF'
server {
    listen 80;
    server_name DOMAIN_INIT;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
INITCONF
sed -i "s/DOMAIN_INIT/$DOMAIN/g" /etc/nginx/sites-available/japan-rpg-init

# Start with HTTP-only config
ln -sf /etc/nginx/sites-available/japan-rpg-init /etc/nginx/sites-enabled/japan-rpg
nginx -t && systemctl restart nginx

# Obtain SSL certificate
info "Requesting Let's Encrypt certificate..."
certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

# Switch to full SSL config
ln -sf /etc/nginx/sites-available/japan-rpg /etc/nginx/sites-enabled/japan-rpg
nginx -t && systemctl reload nginx

info "SSL certificate installed and nginx configured."

# ─── Step 7: Create admin user ───────────────────────────────────────────────

info "Step 7/7 — Setting up admin user..."
USER_COUNT=$(sudo -u "$SERVICE_USER" bash -c "
    cd $INSTALL_DIR
    $INSTALL_DIR/venv/bin/python -c \"
from backend.auth import UserManager
um = UserManager(data_dir='$INSTALL_DIR/data')
print(len(um.list_users()))
\"
" 2>/dev/null || echo "0")

if [[ "$USER_COUNT" == "0" ]]; then
    read -rsp "Choose admin password: " ADMIN_PW
    echo
    sudo -u "$SERVICE_USER" bash -c "
        cd $INSTALL_DIR
        echo '$ADMIN_PW' | $INSTALL_DIR/venv/bin/python -m backend.create_user admin --admin
    "
    info "Admin user 'admin' created."
else
    info "Users already exist — skipping admin creation."
fi

# ─── Set up certbot auto-renewal ─────────────────────────────────────────────

# certbot installs a systemd timer by default, but verify it
if systemctl is-enabled certbot.timer &>/dev/null; then
    info "Certbot auto-renewal timer is active."
else
    systemctl enable --now certbot.timer
    info "Certbot auto-renewal timer enabled."
fi

# Ensure nginx reloads after renewal
RENEWAL_HOOK="/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh"
if [[ ! -f "$RENEWAL_HOOK" ]]; then
    cat > "$RENEWAL_HOOK" <<'HOOK'
#!/bin/bash
systemctl reload nginx
HOOK
    chmod +x "$RENEWAL_HOOK"
    info "Nginx reload hook installed for certificate renewals."
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
info "   systemctl status japan-rpg       # App status"
info "   journalctl -u japan-rpg -f       # App logs (live)"
info "   systemctl restart japan-rpg      # Restart app"
info "   systemctl status nginx           # Nginx status"
info "   certbot certificates             # SSL certificate info"
info "   certbot renew --dry-run          # Test renewal"
info ""
info " Files:"
info "   App:     $INSTALL_DIR/"
info "   Config:  $INSTALL_DIR/.env"
info "   Data:    $INSTALL_DIR/data/"
info "   Nginx:   /etc/nginx/sites-available/japan-rpg"
info "   Service: /etc/systemd/system/japan-rpg.service"
info ""
