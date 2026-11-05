# 个人多 Agent 工作台

面向个人用户：网页登录并管理任务，云端 Agent 负责规划与协作，用户自己的电脑执行明确授权的本地工具。按版本逐步交付，旧项目保持原样。

**当前版本 V0.3：多 Agent、审批与恢复**。在可靠 PostgreSQL 队列与独立 Worker 基础上，增加主 Agent、内容整理/质量检查子 Agent、计划、文档审批、checkpoint 恢复、安全 Markdown 和产物下载。已部署服务器供本人通过 SSH 隧道验证；本地设备连接与公网内测在后续版本推进。

## 从这里开始

先看 [V0.3 架构说明](docs/releases/v0.3/architecture.md) 或 [完整启动手册](docs/releases/v0.3/operations.md)。首次本地运行：

```bash
cd /Users/yangkailiang/Documents/DeepAgents/personal-superagent
uv sync --locked
uv run --locked python scripts/init_dev.py
docker compose --env-file .env.dev up -d --wait
uv run --env-file .env.dev --locked manage.py migrate
uv run --env-file .env.dev --locked manage.py createsuperuser
uv run --env-file .env.dev --locked manage.py runserver 127.0.0.1:8002 --noreload
```

另一个终端进入项目根目录，启动 Worker：

```bash
uv run --env-file .env.dev --locked manage.py agent_worker
```

访问 `http://127.0.0.1:8002/`，离线演示流程为：计划 → 两个子 Agent → 待审批 → 批准后保存/下载，拒绝不发布。固定模型响应仍经过真实编排、工具、审批与 checkpoint，不消耗模型额度。默认 1 并发、全局最多 2；页面关闭不取消任务。

服务器首次使用，在本项目根目录安全建号并开启隧道：

```bash
uv sync --locked --group deploy
uv run --locked --group deploy python scripts/deploy/create_account.py
uv run --locked --group deploy python scripts/deploy/remote.py tunnel
```

保持隧道运行，访问 `http://127.0.0.1:18002/`。没有默认密码，服务器默认只启用离线演示。SSH 凭证仅在忽略的本机 `.server`；服务器密钥、账号、数据均独立于本地，详见启动手册。

[第一课参考](docs/lessons/01-single-agent.md)仍可运行：

```bash
cd /Users/yangkailiang/Documents/DeepAgents/personal-superagent
uv sync --locked
uv run --locked superagent --demo
uv run --locked pytest -q
```

需要 Python 3.12 和 uv。`.venv` 独立，不复用旧项目的依赖环境或密钥。离线模式不调用模型服务；首次安装依赖需要联网。

## 文档入口

- [总纲与边界](docs/00-overview.md)
- [11 月时间表](docs/01-roadmap.md)
- [进度与验收记录](docs/progress.md)
- [技术决策](docs/decisions.md)
- [版本文档：架构、实现、验证、运行与架构问答](docs/releases/README.md)
- [第一课](docs/lessons/01-single-agent.md) / [第二课](docs/lessons/02-django-tasks.md)（历史教学参考）

结果与限制见 [V0.3 验证报告](docs/releases/v0.3/verification.md)。checkpoint 缺失、损坏或版本不兼容时拒绝恢复；恢复同一次执行与新建执行重试明确区分。没有接入本地设备、任意 Shell 或公开注册。
