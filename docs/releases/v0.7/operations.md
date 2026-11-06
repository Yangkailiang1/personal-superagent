# V0.7 运行方法

## 云端 / 本机 Web

继续使用已有 PostgreSQL 与 Django 配置。安装锁定 Python 依赖，执行迁移，构建前端，再分别启动 Web 和 Worker。项目根目录示例：

```bash
uv sync --locked
uv run --env-file .env.dev python manage.py migrate
npm ci --prefix frontend
npm run build --prefix frontend
uv run --env-file .env.dev python manage.py runserver 127.0.0.1:18005
# 另一个终端
uv run --env-file .env.dev python manage.py agent_worker --concurrency 1
```

Node 推荐 24 LTS，执行器要求至少 22。服务器不安装 Claude、不需要模型凭据；通过现有 SSH 隧道访问。不要把本机凭据目录上传到服务器。

## 本机客户端

先安装 Claude Code 并在自己的终端完成 `claude auth login`；此命令需要你交互操作。然后在项目根目录：

```bash
npm ci --prefix executor
npm run build --prefix executor
uv run superagent-client --config-dir ~/.personal-superagent happier-check
```

happier-check 检查登录状态和 SDK 可加载性，不调用付费模型；不代表已经验证真实工具链路。若 auth status 超时，先在普通终端检查 Claude 配置。

在网页“设备与授权”创建配对码，使用页面给出的地址与码绑定（SSH 隧道地址必须保持可用）：

```bash
uv run superagent-client --config-dir ~/.personal-superagent pair --url http://127.0.0.1:18002 --code 页面绑定码 --name 我的电脑
uv run superagent-client --config-dir ~/.personal-superagent happier-repo \
  --name 我的代码仓库 --path /绝对路径/我的仓库 \
  --write-path src --write-path tests --check "python -m pytest" \
  --ack-cloud-transfer
uv run superagent-client --config-dir ~/.personal-superagent happier-run
```

必须选择已有提交的仓库，授权目录不能覆盖客户端凭据目录。登记保存当前提交，运行中的用户未提交修改不进入任务工作区。客户端手动启动才上报可用，不自动后台安装服务。

## 一条完整操作

1. 主对话说明代码目标，形成 Plan。
2. 步骤选择“本机代码执行目标”；确认基线、范围、检查、设备和交付。
3. 点击发布并执行。全代码计划直接使用本机 Claude，云端可不配置模型；混合任务仍需相应云端模型。
4. 看板打开任务，在网页批准/拒绝额外命令。决定送达前显示等待本机确认。
5. 查看差异、文件和检查输出，下载交付报告。任务成功是本机交付完成，不代表代码已合并。
6. 本机 `~/.personal-superagent/worktrees/<attempt-id>` 保留修改；手动评审和 Git 操作。本版不提交、合并或 push。

默认本机每次运行一个任务、全局最多两个。默认每仓库 16 个 SDK turn、任务 1800 秒、单条检查 120 秒。SDK turn 不等于精确模型调用次数；供应商 usage/cost 仅按实际返回展示，不承诺限制整个账户账单。

## 撤销、断线与恢复

```bash
uv run superagent-client --config-dir ~/.personal-superagent happier-revoke --name 我的代码仓库
```

运行客户端同步撤销；运行中也重新读取本机授权。网页取消先发出意图，进程真正停止并回执后才释放归属。断线时终止受管执行、保存回执；重启只补传，不自动重跑。无法确认旧进程时先人工核查，不能直接删账本再重试。

保持原设备、注册文件和本机 SQLite；Claude 会话 ID 供排错，不承诺透明恢复。用户重试创建新 Attempt 和新 worktree。保留未集成修改，不自动清理。

## 部署 / 回退

按现有 scripts/deploy/release.py 发布经过验证的提交：备份 PostgreSQL 与 runtime，执行编号迁移，切换 release，再启动 Web/Worker。Happier 客户端需单独更新 Python 包并安装 executor 依赖。仓库开发模式需完整源码，Python wheel 不捆绑 Node 程序。

停用时停止本机 happier-run，并撤销仓库授权；保留现有 DeepAgents 任务。数据库回退不能直接降级并丢弃新表；恢复旧 release 前核查活动执行并按备份策略处理。

补充：若本机 `uv` 尚未加入 PATH，本工作区可使用 `.artifacts/tooling/bin/uv` 替代上述 `uv`。预授权检查首版支持 Python/pytest、npm/pnpm 测试构建，以及只读 Git/版本检查；删除、安装等操作不能伪装成检查命令。检查输出只保留末尾 20 KB；超时即失败，即使命令处理终止信号后返回 0。
