# Japan-RPG: Kurzanleitung Ubuntu-Setup

Kompakte Einrichtung auf einem Ubuntu VPS (22.04+).
Projektpfad: `/home/jrpg/Japan-RPG`. Ersetze `DEINE-DOMAIN.de` und `DEINE@EMAIL.de` durch deine echten Werte.

## Voraussetzungen

- Ubuntu 22.04+ VPS mit Root/sudo-Zugang
- Domain mit A-Record auf die Server-IP
- Anthropic API-Key

---

## 1. System-Pakete & User

```bash
sudo apt update && sudo apt install -y python3 python3-venv nginx certbot python3-certbot-nginx
sudo useradd --system --create-home --home-dir /home/jrpg --shell /usr/sbin/nologin jrpg
```

## 2. Projekt auf den Server bringen

```bash
# Per git clone:
sudo git clone https://github.com/DEIN-USER/Japan-RPG.git /home/jrpg/Japan-RPG

# Oder per rsync vom lokalen Rechner:
# rsync -az --exclude='.git' --exclude='.env' --exclude='data/users*' \
#   --exclude='__pycache__' --exclude='assets/' ./ root@SERVER:/home/jrpg/Japan-RPG/
```

## 3. Python-Umgebung & Assets

```bash
sudo python3 -m venv /home/jrpg/Japan-RPG/venv
sudo /home/jrpg/Japan-RPG/venv/bin/pip install -r /home/jrpg/Japan-RPG/backend/requirements.txt gunicorn
cd /home/jrpg/Japan-RPG && sudo /home/jrpg/Japan-RPG/venv/bin/python generate_placeholders.py
```

## 4. Konfiguration

```bash
sudo mkdir -p /home/jrpg/Japan-RPG/data/users /home/jrpg/Japan-RPG/data/saves
sudo cp /home/jrpg/Japan-RPG/.env.example /home/jrpg/Japan-RPG/.env
sudo nano /home/jrpg/Japan-RPG/.env
```

Mindestinhalt der `.env`:

```
ANTHROPIC_API_KEY=sk-ant-dein-key-hier
CORS_ORIGIN=https://DEINE-DOMAIN.de
```

```bash
sudo chmod 600 /home/jrpg/Japan-RPG/.env
sudo chown -R jrpg:jrpg /home/jrpg
```

## 5. systemd-Service starten

```bash
sudo cp /home/jrpg/Japan-RPG/deploy/japan-rpg.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now japan-rpg
sudo systemctl status japan-rpg
```

## 6. nginx + SSL

```bash
# Temporaere HTTP-Config fuer certbot
cat << 'EOF' | sudo tee /etc/nginx/sites-available/japan-rpg
server {
    listen 80;
    server_name DEINE-DOMAIN.de;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/japan-rpg /etc/nginx/sites-enabled/
sudo mkdir -p /var/www/certbot
sudo nginx -t && sudo systemctl restart nginx

# SSL-Zertifikat holen
sudo certbot certonly --webroot --webroot-path=/var/www/certbot \
    --email DEINE@EMAIL.de --agree-tos --no-eff-email -d DEINE-DOMAIN.de

# Finale nginx-Config mit SSL aktivieren
sudo sed 's/DOMAIN_PLACEHOLDER/DEINE-DOMAIN.de/g' \
    /home/jrpg/Japan-RPG/deploy/nginx/japan-rpg.conf \
    > /etc/nginx/sites-available/japan-rpg
sudo nginx -t && sudo systemctl reload nginx
```

## 7. Admin-User anlegen

```bash
sudo -u jrpg /home/jrpg/Japan-RPG/venv/bin/python -m backend.create_user admin --admin
```

## 8. Zertifikat-Renewal

```bash
sudo systemctl enable --now certbot.timer
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh << 'EOF'
#!/bin/bash
systemctl reload nginx
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

---

## Fertig

Die App laeuft unter `https://DEINE-DOMAIN.de` — Login unter `/app/login.html`.

## Wichtige Befehle

| Aktion             | Befehl                                |
|--------------------|---------------------------------------|
| Status pruefen     | `systemctl status japan-rpg`          |
| Logs ansehen       | `journalctl -u japan-rpg -f`          |
| Neustarten         | `systemctl restart japan-rpg`         |
| Update einspielen  | `cd /home/jrpg/Japan-RPG && sudo -u jrpg git pull && sudo /home/jrpg/Japan-RPG/venv/bin/pip install -r backend/requirements.txt && sudo systemctl restart japan-rpg` |
