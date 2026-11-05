#!/usr/bin/env bash
# 已核查 Alibaba Cloud Linux 3；只新增本应用环境，不替换系统 Python。
set -euo pipefail
if ! id superagent >/dev/null 2>&1; then
  useradd --system --create-home --shell /bin/bash superagent
fi
install -d -m 0755 -o superagent -g superagent /opt/personal-superagent/releases
install -d -m 0700 -o superagent -g superagent /opt/personal-superagent/shared
install -d -m 0700 -o superagent -g superagent /opt/personal-superagent/shared/runtime
install -d -m 0700 /opt/personal-superagent/backups
cd /home/superagent
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo -o /etc/yum.repos.d/docker-ce.repo
  dnf -y install dnf-plugin-releasever-adapter --repo alinux3-plus
  dnf -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
systemctl enable --now docker
if [ ! -x /home/superagent/.local/bin/uv ]; then
  curl -LsSf https://astral.sh/uv/install.sh -o /tmp/personal-superagent-uv-install.sh
  runuser -u superagent -- env HOME=/home/superagent UV_NO_MODIFY_PATH=1 sh /tmp/personal-superagent-uv-install.sh
fi
runuser -u superagent -- env HOME=/home/superagent /home/superagent/.local/bin/uv python install 3.12
docker --version
runuser -u superagent -- /home/superagent/.local/bin/uv --version
