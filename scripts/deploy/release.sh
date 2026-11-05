#!/usr/bin/env bash
set -euo pipefail
revision="$1"
digest="$2"
base=/opt/personal-superagent
release="$base/releases/$revision"
archive="/tmp/personal-superagent-$revision.tar"
echo "$digest  $archive" | sha256sum --check --status
if [ ! -d "$release" ]; then
  install -d -m 0755 -o superagent -g superagent "$release"
  tar -xf "$archive" -C "$release" --no-same-owner
  chown -R superagent:superagent "$release"
fi
if [ ! -f "$base/shared/runtime.env" ]; then
  # 服务器独立生成凭证；不读取开发电脑密钥或服务器 SSH 密码。
  python3 - <<'PY'
import os, secrets
path='/opt/personal-superagent/shared/runtime.env'
content=('DJANGO_SETTINGS_MODULE=personal_superagent.web.settings_tunnel\n'
         'DJANGO_SECRET_KEY='+secrets.token_hex(32)+'\n'
         'DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1\n'
         'PGDATABASE=personal_superagent\nPGUSER=personal_superagent\n'
         'PGPASSWORD='+secrets.token_hex(24)+'\nPGHOST=127.0.0.1\nPGPORT=55432\n'
         'AGENT_RUNTIME_DIR=/opt/personal-superagent/shared/runtime\nALLOW_REAL_MODE=0\n')
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f: f.write(content)
PY
  chown superagent:superagent "$base/shared/runtime.env"
fi
cd "$release"
runuser -u superagent -- env HOME=/home/superagent /home/superagent/.local/bin/uv sync --locked --no-dev --python 3.12
docker compose --env-file "$base/shared/runtime.env" up -d --wait
# 只停止本应用，避免迁移时并发写。首次安装没有旧服务。
if systemctl cat personal-superagent-worker >/dev/null 2>&1; then systemctl stop personal-superagent-worker; fi
if systemctl cat personal-superagent-web >/dev/null 2>&1; then systemctl stop personal-superagent-web; fi
backup="$base/backups/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$backup"
docker compose --env-file "$base/shared/runtime.env" exec -T postgres pg_dump -U personal_superagent personal_superagent </dev/null > "$backup/database.sql"
tar -cf "$backup/runtime.tar" -C "$base/shared" runtime
runuser -u superagent -- env HOME=/home/superagent /home/superagent/.local/bin/uv run --env-file "$base/shared/runtime.env" --locked --no-dev manage.py migrate
runuser -u superagent -- env HOME=/home/superagent /home/superagent/.local/bin/uv run --env-file "$base/shared/runtime.env" --locked --no-dev manage.py check
ln -sfn "$release" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"
cp "$release/scripts/deploy/personal-superagent-web.service" /etc/systemd/system/
cp "$release/scripts/deploy/personal-superagent-worker.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now personal-superagent-web personal-superagent-worker
sleep 2
systemctl is-active personal-superagent-web personal-superagent-worker
curl -fsS -o /dev/null http://127.0.0.1:8000/accounts/login/
echo "Released $revision; web is loopback-only."
