# Personal Superagent

面向个人用户的多 Agent 工作台：主对话制定 Plan，云端与本机 Agent 按能力执行，用户通过看板跟踪、审批和管理交付。

- [整体技术架构](docs/architecture.md)
- [版本进展](docs/progress.md)
- [Happier 来源与许可](executor/UPSTREAM.md)

## 启动

Python 3.12、uv、PostgreSQL，前端与 Claude 执行器使用 Node.js 22+（推荐 24）。使用本项目独立配置，切勿提交密钥。

```bash
uv sync --locked
uv run --env-file .env.dev python manage.py migrate
npm ci --prefix frontend && npm run build --prefix frontend
uv run --env-file .env.dev python manage.py runserver 127.0.0.1:18005
# 另一终端
uv run --env-file .env.dev python manage.py agent_worker --concurrency 1
```

服务器已部署时，在本机保持 SSH 隧道：

```bash
uv run --group deploy python scripts/deploy/remote.py tunnel --port 18002
```

浏览器访问 `http://127.0.0.1:18002/app/`。账号与任务按用户隔离，不提供默认密码。

## 本机 Blender 工作 Agent

先在网页绑定设备，按页面的配对码执行 `superagent-client pair`；已经配对则复用原配置目录。

```bash
npm ci --prefix executor && npm run build --prefix executor
uv run superagent-client happier-check --live
uv run superagent-client blender-config --output ~/Documents/SuperagentOutputs --ack-model-context
uv run superagent-client blender-run
```

支持读取本机 CC Switch 当前 Claude 连接配置，凭据不传云端。`--live` 会实际调用模型验证工具能力。需已安装 Blender 与兼容 addon（当前协议 15）；每次任务使用独立进程与目录，不覆盖原场景。

云端只保存本机文件追踪，模型与预览留本机。执行设备在线时可在网页请求本机打开。模型调用可能产生费用；失败或结果未知时不自动重试。

本地代码 Agent 仍可使用 `happier-repo` 与 `happier-run`；仅文件工具可使用 `grant` 与 `run`。本机详细操作记录和实现文档不纳入公开仓库。
