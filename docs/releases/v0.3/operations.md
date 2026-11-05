# V0.3 本地与服务器运行

## 本地

```bash
cd /Users/yangkailiang/Documents/DeepAgents/personal-superagent
uv sync --locked
docker compose --env-file .env.dev up -d --wait
uv run --env-file .env.dev --locked manage.py migrate
uv run --env-file .env.dev --locked manage.py runserver 127.0.0.1:8002 --noreload
```

另一个终端：

```bash
uv run --env-file .env.dev --locked manage.py agent_worker
```

原账号照常使用。新安装先运行 `scripts/init_dev.py` 和 createsuperuser，见 V0.2 手册。运行文件默认在忽略目录 `.runtime`，不要删除仍需审批/恢复的 checkpoint。

创建任务并选择离线演示：计划 → writer → reviewer → 待审批。批准则保存 Markdown，拒绝则仅返回说明。关闭网页或停止 Worker 不影响待审批记录；启动 Worker 后批准继续。

真实模式需要本项目 MODEL_API_KEY/MODEL_NAME，可选 MODEL_BASE_URL；配置变化会阻止恢复旧执行，API Key 轮换不改变兼容指纹。本次验证不调用付费供应商。

## 服务器：仅本人通过 SSH 隧道访问

服务器凭证只在本机 `.server`，已忽略并设为 0600。SSH 主机指纹已固定在部署脚本，连接时核对，不使用无条件信任未知主机。没有使用 Workbench CLI，因为当前未配置阿里云 AK。

在项目根目录执行：

```bash
uv sync --locked --group deploy
uv run --locked --group deploy python scripts/deploy/remote.py tunnel
```

保持终端运行，然后访问 `http://127.0.0.1:18002/`。隧道关闭只影响访问，不停止服务器任务。

首次使用请自己在安全终端创建账号：

```bash
uv run --locked --group deploy python scripts/deploy/create_account.py
```

脚本让你本地输入用户名和两次隐藏密码，校验密码强度，经 SSH stdin 创建普通账号；没有默认密码，也不会覆盖已有用户。临时验收账号不会保留。

## 服务与目录

- Web：systemd `personal-superagent-web`，Gunicorn 一个 worker、两个线程，监听服务器 `127.0.0.1:8000`。
- 执行：systemd `personal-superagent-worker`，默认一并发、每段活跃执行超时 1800 秒。
- 数据库：专用 PostgreSQL Docker 容器，监听 `127.0.0.1:55432`，无公网映射。
- `/opt/personal-superagent/releases/<提交号>`：只读发布来源（应用用户拥有运行环境）；`current` 指向当前提交。
- `shared/runtime.env`：服务器独立密钥/数据库配置，0600；`shared/runtime`：0700 checkpoint。
- `backups/<时间>`：迁移前 PostgreSQL dump 和运行文件归档，root 专用。

默认 `ALLOW_REAL_MODE=0`，服务端同时拒绝真实模式启动，避免误选消耗额度。开启真实模式需由本人配置服务器独立模型密钥并改为 1，之后重启本应用服务。不要把模型密钥写进 .server、Git、命令行或聊天。

## 后续发布与回退

```bash
uv run --locked --group deploy python scripts/deploy/remote.py bootstrap
uv run --locked --group deploy python scripts/deploy/release.py
```

bootstrap 幂等安装缺少的 Docker、uv 与独立 Python，不替换系统 Python。release 只打包 git HEAD，计算 SHA256，经 SSH 上传校验；不上传 .server/.env/数据。它会短暂停止本应用，备份数据库和 checkpoint、迁移、切换 current 并启动服务。

如果迁移失败，不强行回滚数据库或删除当前数据。保留备份与旧发布目录，先检查日志与迁移兼容性；代码回退只有在数据库兼容确认后才切换旧目录。checkpoint 源码指纹不兼容时，旧任务不能在新代码上直接续跑；需要回到兼容版本或新建执行。

本机 PostgreSQL 与服务器数据库相互独立，没有迁移本地用户和历史。

## 常用检查

```bash
uv run --group deploy python scripts/deploy/remote.py exec 'systemctl is-active personal-superagent-web personal-superagent-worker'
uv run --group deploy python scripts/deploy/remote.py exec 'journalctl -u personal-superagent-worker -n 40 --no-pager'
```

不要输出 runtime.env 或原始模型异常。应用只用普通用户运行，不加入 docker 用户组。SSH 隧道配置允许本机 HTTP Cookie，因为加密由 SSH 承担；不得因此把 8000 绑定到公网。公网邀请内测仍需要 HTTPS、限速、配额、监控和备份恢复演练，留在 V0.5。
