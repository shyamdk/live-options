#!/usr/bin/env bash
set -euo pipefail

APP_ROOT=/opt/live-options
PUBLIC_URL=http://140.245.25.236
RELEASE_ID=$(date +%Y%m%d%H%M%S)
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_ID"

sudo mkdir -p "$APP_ROOT/releases" "$APP_ROOT/shared/data"
sudo chown -R opc:opc "$APP_ROOT"

mkdir -p "$RELEASE_DIR"
tar -xzf /tmp/live-options-deploy.tar.gz -C "$RELEASE_DIR"

# Keep production credentials outside versioned releases. On the first deploy
# using shared env storage, preserve the current release's existing settings.
if [ ! -f "$APP_ROOT/shared/.env" ]; then
  if [ ! -f "$APP_ROOT/current/.env" ]; then
    echo "No shared or current production .env found; refusing to deploy without credentials." >&2
    exit 1
  fi
  cp -p "$APP_ROOT/current/.env" "$APP_ROOT/shared/.env"
fi
if [ -e "$RELEASE_DIR/.env" ] || [ -L "$RELEASE_DIR/.env" ]; then
  echo "Deployment archive must not contain .env; refusing to replace production credentials." >&2
  exit 1
fi
ln -s "$APP_ROOT/shared/.env" "$RELEASE_DIR/.env"
chmod 600 "$APP_ROOT/shared/.env"

python3.12 -m venv "$RELEASE_DIR/.venv"
"$RELEASE_DIR/.venv/bin/python" -m pip install --upgrade pip
"$RELEASE_DIR/.venv/bin/python" -m pip install -r "$RELEASE_DIR/backend/requirements.txt"
# headless Chromium for the automated Kite login; kept outside releases so it is downloaded once
# (system libraries: nss atk at-spi2-atk cups-libs libdrm libxkbcommon libXcomposite libXdamage libXfixes libXrandr mesa-libgbm pango alsa-lib)
sudo mkdir -p /opt/live-options/shared/ms-playwright && sudo chown "$(id -un)" /opt/live-options/shared/ms-playwright
PLAYWRIGHT_BROWSERS_PATH=/opt/live-options/shared/ms-playwright "$RELEASE_DIR/.venv/bin/python" -m playwright install chromium >/dev/null 2>&1 || echo "playwright chromium install failed (Kite auto-login will fall back to the Telegram link)"

cd "$RELEASE_DIR/frontend"
npm ci --no-audit --no-fund
NEXT_PUBLIC_API_BASE_URL="$PUBLIC_URL" npm run build

ln -sfn "$RELEASE_DIR" "$APP_ROOT/current"

sudo tee /etc/systemd/system/live-options-backend.service >/dev/null <<'UNIT'
[Unit]
Description=Live Options FastAPI backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=opc
WorkingDirectory=/opt/live-options/current/backend
Environment=PYTHONPATH=/opt/live-options/current/backend
Environment=DATABASE_FILE=/opt/live-options/shared/data/live_options.sqlite3
ExecStart=/opt/live-options/current/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo tee /etc/systemd/system/live-options-frontend.service >/dev/null <<'UNIT'
[Unit]
Description=Live Options Next.js frontend
After=network-online.target live-options-backend.service
Wants=network-online.target

[Service]
Type=simple
User=opc
WorkingDirectory=/opt/live-options/current/frontend
Environment=NODE_ENV=production
ExecStart=/usr/bin/npm run start -- --hostname 127.0.0.1 --port 3000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo tee /etc/nginx/conf.d/live-options.conf >/dev/null <<'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name 140.245.25.236;

    client_max_body_size 10m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Equity's cold-cache portfolio build fans out per holding (Screener
        # scrapes + Dhan historical calls) and measured ~90s locally -- nginx's
        # 60s default proxy_read_timeout was cutting that request off before
        # the backend finished (confirmed: "upstream timed out (110)" in
        # error.log). 130s covers a cold load with margin.
        proxy_connect_timeout 10s;
        proxy_send_timeout 130s;
        proxy_read_timeout 130s;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
NGINX

if command -v setsebool >/dev/null 2>&1; then
  sudo setsebool -P httpd_can_network_connect 1 || true
fi

if command -v firewall-cmd >/dev/null 2>&1; then
  sudo firewall-cmd --add-service=http --permanent || true
  sudo firewall-cmd --reload || true
fi

sudo systemctl daemon-reload
sudo systemctl enable --now live-options-backend.service
sudo systemctl restart live-options-backend.service
sudo systemctl enable --now live-options-frontend.service
sudo systemctl restart live-options-frontend.service
# HTTPS twin of the site for Kite's login redirect (Kite only accepts https redirect URLs).
# Certificate: Let's Encrypt for 140-245-25-236.sslip.io via certbot (renewed by certbot-renew.timer).
CERT_HOST=140-245-25-236.sslip.io
if sudo test -f "/etc/letsencrypt/live/$CERT_HOST/fullchain.pem"; then
  sudo python3 - "$CERT_HOST" <<'PY'
import sys
host = sys.argv[1]
src = open("/etc/nginx/conf.d/live-options.conf").read()
head = "    listen 80;\n    listen [::]:80;\n    server_name 140.245.25.236;"
assert head in src
out = src.replace(head, f"    listen 443 ssl;\n    listen [::]:443 ssl;\n    server_name {host};\n\n"
                  f"    ssl_certificate /etc/letsencrypt/live/{host}/fullchain.pem;\n"
                  f"    ssl_certificate_key /etc/letsencrypt/live/{host}/privkey.pem;\n"
                  "    ssl_protocols TLSv1.2 TLSv1.3;", 1)
open("/etc/nginx/conf.d/live-options-ssl.conf", "w").write("# HTTPS for live-options (Kite login redirect). Regenerated by deploy_oci.sh.\n" + out)
PY
fi
sudo nginx -t
sudo systemctl enable --now nginx.service
sudo systemctl restart nginx.service

sleep 3
systemctl --no-pager --full status live-options-backend.service | sed -n '1,18p'
systemctl --no-pager --full status live-options-frontend.service | sed -n '1,18p'
systemctl --no-pager --full status nginx.service | sed -n '1,18p'
# The backend takes a few seconds to finish startup after restart; retry
# instead of failing the deploy (and skipping release cleanup) on a race.
for attempt in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8000/health && break
  [ "$attempt" -eq 30 ] && exit 1
  sleep 1
done
curl -fsS -o /dev/null -w '\nlocal_http=%{http_code}\n' http://127.0.0.1/

# Retain the active release and two rollback candidates after health checks pass.
CURRENT_RELEASE=$(readlink -f "$APP_ROOT/current")
PREVIOUS_RELEASES=0
while IFS= read -r RELEASE; do
  [ "$RELEASE" = "$CURRENT_RELEASE" ] && continue
  PREVIOUS_RELEASES=$((PREVIOUS_RELEASES + 1))
  if [ "$PREVIOUS_RELEASES" -gt 2 ]; then
    rm -rf -- "$RELEASE"
  fi
done < <(find "$APP_ROOT/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)

echo "Deployed release $RELEASE_ID"
