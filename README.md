# 个人多 Agent 工作台

面向个人用户：网页登录并管理任务，云端 Agent 负责规划与协作，用户自己的电脑执行明确授权的本地工具。按课程逐步实现，旧项目保持原样。

**当前推进到第二课参考实现**：Django 登录、任务创建与用户隔离。尚未接入后台 Worker、设备连接或多 Agent 调度。

## 从这里开始

已熟悉 Agent 基础可直接阅读 [第二课：Django 登录与任务](docs/lessons/02-django-tasks.md)：

```bash
cd /Users/yangkailiang/Documents/DeepAgents/personal-superagent
uv sync --locked
uv run --locked manage.py migrate --settings=personal_superagent.web.settings_local
uv run --locked manage.py createsuperuser --settings=personal_superagent.web.settings_local
uv run --locked manage.py runserver 127.0.0.1:8001 --settings=personal_superagent.web.settings_local
```

访问 `http://127.0.0.1:8001/`。这是显式 SQLite 本地教学配置；PostgreSQL 路径见讲义，不会自动回退数据库。任务目前只保存、不执行。

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

Django 应用与 PostgreSQL 驱动已经加入；本地测试尚不代表 PostgreSQL 并发验证。持久化 checkpoint、后台 Worker 在下一课接入。
