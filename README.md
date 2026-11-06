# 个人多 Agent 工作台

面向个人用户：网页登录并管理任务，云端 Agent 负责规划与协作，用户自己的电脑执行明确授权的本地工具。按版本逐步交付，旧项目保持原样。

**当前版本 V0.5：需求对话与任务看板**。接待 Agent 整理草稿，用户确认后生成待启动任务，后台 Agent 执行并通过六列 Dashboard 展示真实阶段；保留本地工具、审批和历史恢复。真实模型支持独立安全配置与显式工具验证，未配置时仅演示，服务器仍供本人通过 SSH 隧道使用。

## 从这里开始

先看 [V0.5 架构说明](docs/releases/v0.5/architecture.md) 或 [完整启动手册](docs/releases/v0.5/operations.md)。首次本地运行：

```bash
cd /Users/yangkailiang/Documents/DeepAgents/personal-superagent
uv sync --locked
uv run --locked python scripts/init_dev.py
docker compose --env-file .env.dev up -d --wait
uv run --env-file .env.dev --locked manage.py migrate
uv run --env-file .env.dev --locked manage.py createsuperuser
npm ci --prefix frontend
npm run build --prefix frontend # Node 24
uv run --env-file .env.dev --locked manage.py runserver 127.0.0.1:8002 --noreload
```

另一个终端进入项目根目录，启动 Worker：

```bash
uv run --env-file .env.dev --locked manage.py agent_worker
```

访问 `http://127.0.0.1:8002/app/`，离线演示流程为：计划 → 两个子 Agent → 待审批 → 批准后保存/下载，拒绝不发布。固定模型响应仍经过真实编排、工具、审批与 checkpoint，不消耗模型额度。默认 1 并发、全局最多 2；页面关闭不取消任务。

服务器首次使用，在本项目根目录安全建号并开启隧道：

```bash
uv sync --locked --group deploy
uv run --locked --group deploy python scripts/deploy/create_account.py
uv run --locked --group deploy python scripts/deploy/remote.py tunnel
```

保持隧道运行，访问 `http://127.0.0.1:18002/app/`。没有默认密码，服务器默认只启用离线演示。SSH 凭证仅在忽略的本机 `.server`；服务器密钥、账号、数据均独立于本地，详见启动手册。

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

模型配置、需求对话及看板使用见 [V0.5 运行手册](docs/releases/v0.5/operations.md)，实际结果与未验证项见 [验证报告](docs/releases/v0.5/verification.md)。设备接入沿用 [V0.4 手册](docs/releases/v0.4/operations.md)。未知本地操作不重放，写入仍需审批；未开放公开注册或任意 Shell。
