# Japan-RPG: Manuelle Server-Einrichtung

Schritt-für-Schritt-Anleitung für Debian/Ubuntu VPS.
Ersetze `deine-domain.de` und `deine@email.de` überall durch deine echten Werte.

---

## Voraussetzungen

- Debian 12 / Ubuntu 22.04+ VPS
- Domain zeigt per A-Record auf die Server-IP
- SSH-Zugang als root (oder User mit sudo)
- Anthropic API-Key

---

## 1. System-Pakete installieren

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx rsync
```

## 2. Service-User anlegen

```bash
sudo useradd --system --create-home --home-dir /home/jrpg --shell /usr/sbin/nologin jrpg
```

## 3. Projekt-Dateien kopieren

Vom lokalen Rechner aus (oder aus dem Git-Clone auf dem Server):

```bash
# Option A: Vom lokalen Rechner per rsync
rsync -az --delete \
    --exclude='.git' \
    --exclude='.env' \
    --exclude='data/users/' \
    --exclude='data/users.json' \
    --exclude='data/.jwt_secret' \
    --exclude='data/saves/' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='assets/' \
    ./ root@dein-server:/home/jrpg/

# Option B: Direkt auf dem Server klonen
sudo -u jrpg git clone https://github.com/dein-user/Japan-RPG.git /home/jrpg
```

## 4. Python-Umgebung einrichten

```bash
cd /home/jrpg
sudo python3 -m venv /home/jrpg/venv
sudo /home/jrpg/venv/bin/pip install --upgrade pip
sudo /home/jrpg/venv/bin/pip install -r /home/jrpg/backend/requirements.txt gunicorn
```

## 5. Placeholder-Assets generieren

```bash
cd /home/jrpg
sudo /home/jrpg/venv/bin/python generate_placeholders.py
```

## 6. Daten-Verzeichnisse anlegen

```bash
sudo mkdir -p /home/jrpg/data/users /home/jrpg/data/saves
```

## 7. .env konfigurieren

```bash
sudo cp /home/jrpg/.env.example /home/jrpg/.env
sudo nano /home/jrpg/.env
```

Inhalt:

```
ANTHROPIC_API_KEY=sk-ant-dein-key-hier
CORS_ORIGIN=https://deine-domain.de
```

Berechtigungen setzen:

```bash
sudo chmod 600 /home/jrpg/.env
```

## 8. Dateien dem User jrpg übergeben

```bash
sudo chown -R jrpg:jrpg /home/jrpg
```

## 9. systemd-Service einrichten

```bash
sudo cp /home/jrpg/deploy/japan-rpg.service /etc/systemd/system/japan-rpg.service
sudo systemctl daemon-reload
sudo systemctl enable japan-rpg
sudo systemctl start japan-rpg
```

Prüfen ob er läuft:

```bash
sudo systemctl status japan-rpg
# Bei Problemen:
sudo journalctl -u japan-rpg -f
```

## 10. nginx — erst HTTP-only für Zertifikat

Temporäre Config damit certbot den ACME-Challenge bedienen kann:

```bash
cat << 'EOF' | sudo tee /etc/nginx/sites-available/japan-rpg-init
server {
    listen 80;
    server_name deine-domain.de;

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
EOF
```

Aktivieren:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/japan-rpg-init /etc/nginx/sites-enabled/japan-rpg
sudo mkdir -p /var/www/certbot
sudo nginx -t && sudo systemctl restart nginx
```

Testen (sollte die App über HTTP erreichbar sein):

```
http://deine-domain.de
```

## 11. SSL-Zertifikat holen

```bash
sudo certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email deine@email.de \
    --agree-tos \
    --no-eff-email \
    -d deine-domain.de
```

## 12. nginx — finale SSL-Config

```bash
# Domain-Placeholder ersetzen und als finale Config speichern
sudo sed 's/DOMAIN_PLACEHOLDER/deine-domain.de/g' \
    /home/jrpg/deploy/nginx/japan-rpg.conf \
    > /etc/nginx/sites-available/japan-rpg

# Auf die finale Config umschalten
sudo ln -sf /etc/nginx/sites-available/japan-rpg /etc/nginx/sites-enabled/japan-rpg
sudo nginx -t && sudo systemctl reload nginx
```

Testen:

```
https://deine-domain.de
```

## 13. Admin-User anlegen

```bash
sudo -u jrpg /home/jrpg/venv/bin/python -m backend.create_user admin --admin
```

Du wirst nach Spielername und Passwort (min. 8 Zeichen) gefragt.

## 14. Zertifikat-Auto-Renewal

```bash
# Prüfen ob certbot-Timer aktiv ist
sudo systemctl is-enabled certbot.timer

# Falls nicht:
sudo systemctl enable --now certbot.timer

# Reload-Hook damit nginx das neue Zertifikat auch nutzt
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh << 'EOF'
#!/bin/bash
systemctl reload nginx
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

# Test-Renewal
sudo certbot renew --dry-run
```

---

## Fertig

| Was           | Wo                                       |
|---------------|------------------------------------------|
| App-URL       | `https://deine-domain.de`                |
| Login         | `https://deine-domain.de/app/login.html` |
| App-Dateien   | `/home/jrpg/`                            |
| Config        | `/home/jrpg/.env`                        |
| Spieldaten    | `/home/jrpg/data/`                       |
| nginx-Config  | `/etc/nginx/sites-available/japan-rpg`   |
| systemd-Unit  | `/etc/systemd/system/japan-rpg.service`  |
| Logs          | `journalctl -u japan-rpg -f`             |

## Nützliche Befehle

```bash
sudo systemctl status japan-rpg       # App-Status
sudo systemctl restart japan-rpg      # App neustarten
sudo journalctl -u japan-rpg -f       # Logs live
sudo systemctl status nginx           # nginx-Status
sudo certbot certificates             # Zertifikat-Info
sudo certbot renew --dry-run          # Renewal testen
```

## Update deployen

```bash
# Neue Dateien kopieren (vom lokalen Rechner oder git pull)
cd /home/jrpg
sudo -u jrpg git pull   # falls per git

# Abhängigkeiten aktualisieren (falls requirements.txt geändert)
sudo /home/jrpg/venv/bin/pip install -r /home/jrpg/backend/requirements.txt

# Neustart
sudo systemctl restart japan-rpg
```
