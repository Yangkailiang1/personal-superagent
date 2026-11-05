# V0.4 运行与设备接入

## 启动网页

当前服务器保持本人 SSH 隧道模式，不开放公网 HTTP。沿用原账号，不迁移数据。

```bash
cd /Users/yangkailiang/Documents/DeepAgents/personal-superagent
uv sync --locked --group deploy
uv run --locked --group deploy python scripts/deploy/remote.py tunnel
```

保持终端运行，打开 **http://127.0.0.1:18002/app/**。新安装账号仍用 `scripts/deploy/create_account.py`，不会留下默认密码。旧简易入口 `/` 保留。

## 在自己的电脑绑定

本版客户端支持 macOS / Linux / WSL2，原生 Windows 请进入 WSL2。云端只调用模型，本地不需要模型 Key。客户端从项目源码运行，Python 3.12 与 uv 足够，不需要 Node。

1. 网页进入“设备与授权”，点击“绑定设备”，获取 10 分钟有效的单次绑定码。
2. 在本机项目目录执行（替换绑定码）：

```bash
uv run --locked superagent-client pair \
  --url http://127.0.0.1:18002 \
  --code 这里填写网页绑定码 --name 我的电脑
```

该地址依赖当前电脑的 SSH 隧道。将来公网服务改为 HTTPS 时换服务器 URL；客户端拒绝普通公网 HTTP。不同电脑分别绑定，不复制 client.json。token 不打印、不粘到聊天。

## 授权一个测试目录

先自己创建一个专用目录，放入 UTF-8 `input.md`。不要授权 home、系统根目录、密钥目录；包含客户端凭证目录的授权会被拒绝。

默认只授权列表和读取：

```bash
uv run --locked superagent-client grant \
  --name 我的笔记 --path /你的绝对路径/agent-notes \
  --ack-cloud-transfer
uv run --locked superagent-client run
```

`--ack-cloud-transfer` 表示你知道读取内容将发往云端，并可能进入模型。终端保持运行，客户端每 2 秒主动轮询，不开放本机入站端口。离线判断约 20 秒，不是进程退出瞬间。

若确实需要新建文件，先撤销旧授权，再明确增加写工具：

```bash
uv run --locked superagent-client revoke --name 我的笔记
uv run --locked superagent-client grant \
  --name 我的笔记 --path /你的绝对路径/agent-notes \
  --tools list_files,read_text,write_text --ack-cloud-transfer
```

写入仅新建，不覆盖；每次云端写请求仍需网页批准。修改授权后请创建新任务，旧任务的范围冻结，不能偷偷扩大。

## 创建与执行任务

工作台输入目标，选择“设备 / 授权目录”，材料文件填相对路径（默认 input.md）。创建后确认范围并启动。没有设备的任务仍可选择“仅云端”。

演示链路固定为：计划 → 列目录 → 读材料 → writer/reviewer → 申请在本机新建 superagent-result.md（若授权写入）→ 申请云端保存交付文档 → 最终回答。演示明确标注固定模型，不消耗额度；本地文件操作是真的。

设备离线时显示等待，不回退到服务器目录。恢复客户端会领取尚未开始的操作；已经 leased/结果未知的操作不会被重新执行。

## 撤销、失败与未知结果

- 网页可撤销某个目录或解绑设备；旧客户端不能通过同步重新启用。重新授权须在本机显式操作。
- 也可本机 revoke；下一次轮询同步，工具开始前还会重新读取本地配置。
- 已经开始的写入可能在撤销/取消时完成，无法撤回。查看“执行过程”的本地操作记录。
- uncertain 表示可能已生效但未确认，不等于失败。先检查本机文件，再取消旧任务并决定是否新建执行；不要直接删账本以强行重放。
- 目标文件已存在时 write_text 报错，原内容不变。需要另一个输出文件时创建明确的新任务，不自动覆盖。
- 读取限制 64 KiB、UTF-8 普通文件，拒绝路径越界与符号链接。工具 10 秒超时，云端操作租约 30 秒。

## 本机文件与进程

默认 `~/.personal-superagent/`：client.json（0600，token + 本地根路径）、operations.sqlite3（0600，操作账本）、run.lock。目录 0700。`status` 不打印 token 或本地绝对路径。

```bash
uv run --locked superagent-client status
uv run --locked superagent-client --config-dir /独立配置目录 run
```

同一配置只允许运行一个实例。Ctrl+C 停止，不会自动注销设备；若操作正在开始/执行，保留账本，重启只报告已知结果或未知，不重放。

## 本地开发 / 验证 / 发布

```bash
uv sync --locked --group browser --group deploy
docker compose --env-file .env.dev up -d --wait
uv run --env-file .env.dev --locked manage.py migrate
# 使用 Node 24 构建，或先 nvm use 24
npm ci --prefix frontend
npm run build --prefix frontend
uv run --env-file .env.dev --locked manage.py runserver 127.0.0.1:8002 --noreload
# 另一个终端
uv run --env-file .env.dev --locked manage.py agent_worker
```

本地访问 http://127.0.0.1:8002/app/。修改 Python 后重启服务；非自动重载服务的模板也会缓存。

测试：`manage.py test personal_superagent.tasks personal_superagent.execution personal_superagent.devices personal_superagent.web.tests`（配合 .env.dev）以及 `uv run pytest -q`。浏览器验收用 scripts/browser_v04.py，必须使用专用临时账号与测试目录，不在真实资料目录执行。

发布继续用 `scripts/deploy/release.py`，先提交并测试代码；本机构建后上传静态资源，服务器不需要 Node。迁移前备份数据库与 checkpoint，保留现有账号和 V0.3 图恢复；不自动回滚数据库。

本人 SSH 隧道部署不是多用户公网开放。邀请内测前还需要 HTTPS、登录限速、配额、设备凭证治理和备份恢复演练，不能向其他用户分发 SSH root 凭证。


### 一条完整示例

在终端新建测试材料（已有目录请换一个名字，不覆盖旧资料）：

```bash
mkdir "$HOME/superagent-v04-notes"
# 用文本编辑器在该目录创建 input.md，写入三项学习目标。
uv run --locked superagent-client grant \
  --name 学习笔记 --path "$HOME/superagent-v04-notes" \
  --tools list_files,read_text,write_text --ack-cloud-transfer
uv run --locked superagent-client run
```

网页选择这个目录，输入“阅读 input.md，整理一份学习计划并检查”。点击创建、启动。第一次待审批时看清“本地新建文件”的目录标签、相对路径及正文，批准后检查本机 superagent-result.md。第二次审批是保存云端交付文档，批准后可在线预览和下载。整个过程可以关闭网页后重新登录查看；客户端关闭则后续本地步骤等待。

再次执行演示时目标文件已存在会被明确拒绝，不会覆盖；请为下一次验收使用新的专用测试目录。真实模式使用当前范围内的工具与用户目标，只有显式配置并允许时才调用付费模型。
