# 个人多 Agent 工作台

面向个人用户：网页登录并管理任务，云端 Agent 负责规划与协作，用户自己的电脑执行明确授权的本地工具。按版本逐步交付，旧项目保持原样。

**当前版本 V0.2：可靠任务执行**。已实现 Django 登录、任务隔离、PostgreSQL 队列、独立 Worker/子进程、幂等启动、取消、超时、中断核验、重试历史和事件展示。多 Agent、审批/checkpoint 与本地设备连接仍按后续版本推进。

## 从这里开始

先看 [架构说明](docs/releases/v0.2/architecture.md) 或 [完整启动手册](docs/releases/v0.2/operations.md)。首次运行：

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

访问 `http://127.0.0.1:8002/`，创建任务后选择离线演示即可验证链路，不消耗模型额度。真实模式需要自己的模型配置，见启动手册。默认 1 并发、全局最多 2；页面关闭不会取消任务。本地配置不供公网部署。

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

本版实际验证 PostgreSQL 和真实子进程，不将 SQLite/模拟结果冒充生产验收；结果与限制见版本验证报告。持久化 checkpoint 与多 Agent 在 V0.3 接入。
