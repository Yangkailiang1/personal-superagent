# V0.2 启动与操作

## 首次准备

需要 Python 3.12、uv、Docker（本地仅用来运行 PostgreSQL）。不使用 Docker 执行 Agent，Agent 在本机独立 Python 进程运行。

```bash
cd /Users/yangkailiang/Documents/DeepAgents/personal-superagent
uv sync --locked
uv run --locked python scripts/init_dev.py
docker compose --env-file .env.dev up -d --wait
uv run --env-file .env.dev --locked manage.py migrate
uv run --env-file .env.dev --locked manage.py createsuperuser
```

初始化只在 `.env.dev` 不存在时写入随机项目密钥和数据库密码；不读取或覆盖已有 `.env`。该文件已 gitignore、权限为 0600，不提交也不发进聊天。注意 Compose 初始化密码只在空数据卷生效；已有数据卷密码不能靠改环境变量完成修改。

默认 PostgreSQL 仅绑定 `127.0.0.1:55432`，独立命名卷保存数据。镜像使用已经验证的 PostgreSQL 16 Alpine digest，更新时重新验证。端口冲突时修改 `.env.dev` 的 PGPORT；应用与 Compose 使用同一个文件。

## 启动两个终端

网页：

```bash
uv run --env-file .env.dev --locked manage.py runserver 127.0.0.1:8002 --noreload
```

Worker：

```bash
uv run --env-file .env.dev --locked manage.py agent_worker
```

打开 `http://127.0.0.1:8002/`。这两个命令必须在项目根目录运行。Worker 默认 1 并发、单任务 1800 秒；可加 `--concurrency 2 --timeout 1800`，全局仍最多 2。`--once` 用于处理完当前可领取队列后退出，常驻服务不要用这个参数。

SQLite 教学配置仍可浏览，但执行 Worker 会明确拒绝。不要继续使用第二课的 `settings_local` 来启动正式任务执行链路。

## 完整示例

1. 登录，新建“整理一次短途出行需求”，填入想整理的文字。
2. 选择“离线演示”并启动；看到排队、运行、成功。
3. 展开过程，可以看到真实工具调用；回答明确标注离线，只统计任务文本，不假装完成旅行预订。
4. 关闭页面再打开，状态和结果从数据库恢复。停止 Worker 后新任务只排队，不回退到 HTTP 同步执行。
5. 新建另一任务，排队时取消，再点击“新建执行并重试”。详情保留两次执行。

## 可选真实模型

在 `.env.dev` 中添加本项目自己的 `MODEL_API_KEY`、`MODEL_NAME`、可选 `MODEL_BASE_URL`，然后重启 Worker；不需要读旧项目密钥。选择真实模式会访问供应商并可能收费，本次自动验收未进行付费调用。

真实业务 Agent 本版只允许加法和文本统计，可阅读、整理用户直接提供的文字并回答，不能访问文件、搜索、执行代码或操作设备。供应商不支持工具调用会报失败，不静默丢掉工具或切换离线。

## 检查与测试

```bash
uv run --env-file .env.dev --locked manage.py check
uv run --env-file .env.dev --locked manage.py makemigrations --check --dry-run
uv run --env-file .env.dev --locked manage.py test personal_superagent.tasks personal_superagent.execution --noinput
uv run --locked pytest -q
```

测试连接本项目数据库服务器并创建独立 `test_...` 数据库；开发数据库用户需有建测试库权限，不能对生产库执行这套测试。Compose 创建的开发账号具备该权限，不能照搬到公网生产。

浏览器验收脚本另需 `uv sync --locked --group browser` 和 `uv run playwright install chromium`。提供测试账号的 `BROWSER_TEST_USER`、`BROWSER_TEST_PASSWORD`，运行 `uv run --env-file .env.dev --locked --group browser python scripts/browser_smoke.py`。默认页面端口 8002，使用专用测试账号，脚本会创建演示任务并启动临时 Worker；截图在忽略目录 `.artifacts`。不要在生产执行。

## 停止与故障

- 网页/Worker 各自 Ctrl+C。Worker 正常退出会停止受管子进程并标中断，不自动重试。
- Worker 被强杀后，子进程发现管道断开自行退出。重新启动原主机 Worker，过期后标中断并核验进程；一般最多等待 20 秒租约期。
- 无法确认进程停止时，重试被阻止，不通过手改数据库强行绕过。检查原主机、进程访问权限与 Worker 是否恢复。
- 数据库关闭时 Worker 可能退出；恢复数据库后重启 Worker，再按上述流程处理，不假定它透明续跑。
- `docker compose --env-file .env.dev stop` 停止数据库但保留卷。不要使用 `down -v`，它会删除数据。

## 部署边界

当前 runserver 与 dev 设置仅供本机开发；公网需要 HTTPS、生产 WSGI 服务、进程管理、登录限速、邀请建号、配额与备份恢复，这些在 V0.5 完整交付。2 核 2 GB 默认先 1 并发，内存尚未压测，不保证能支撑 2 个真实模型任务。
