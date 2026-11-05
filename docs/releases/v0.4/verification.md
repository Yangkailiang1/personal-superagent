# V0.4 验证报告

日期：2026-11-05，macOS 本机 + Alibaba Cloud Linux 3 服务器。服务器演示模式，未调用付费模型或生图服务。

## 自动验证

| 验证 | 实际结果 |
| --- | --- |
| `uv run --env-file .env.dev --locked manage.py test personal_superagent.tasks personal_superagent.execution personal_superagent.devices personal_superagent.web.tests --noinput` | 42 项通过，85.103 秒；真实独立 PostgreSQL 测试库，无 SQLite 替代领取测试 |
| `uv run --locked pytest -q` | 24 项通过，3.53 秒；真实 DeepAgents 图、文件工具及账本 |
| `manage.py makemigrations --check --dry-run` | 无遗漏迁移 |
| `ruff check src/personal_superagent --select F` / `git diff --check` | 通过 |
| Node 24：`npm run build --prefix frontend` | TypeScript 检查和 Vite 构建通过；lockfile 安装成功 |
| V0.3 图兼容 | 冻结源码与 aa75c6e 原部署逐文件字节一致，旧版待审批 checkpoint 实际恢复测试通过 |

新增测试覆盖：绑定码过期/单次使用、仅保存凭证哈希、设备 Bearer 与浏览器 CSRF 分离、跨用户目录与任务拒绝、撤销不被同步复活、会话替换、租约不自动重领、回执幂等、取消后迟到结果。真实 HTTP + Worker 子进程 + 客户端测试验证读取材料、子 Agent 使用实际内容、批准前无本地文件、批准后实际新建，以及云端产物包含材料哨兵。

客户端验证覆盖真实 UTF-8 读写、拒绝覆盖、绝对/穿越路径、符号链接、根目录替换、读取大小、未授权工具、凭证目录保护、started 崩溃不重放、同 ID 参数变更拒绝、仅允许 HTTPS 或 loopback HTTP。静态文件额外验证 gzip 内容完整、q=0、Vary 和越界/符号链接拒绝。

## 浏览器与服务器

本机 Chromium 已完成登录 → 绑定 → 授权临时目录 → 新建/启动任务 → 读取 → 两个子 Agent → 本地写审批 → 实际写文件 → 云端保存审批 → 产物预览/下载。所有本机写入都位于脚本 TemporaryDirectory，不授权真实资料目录。服务器 Chromium 全流程同样通过：实际读取本机哨兵材料、审批后新建文件、云端产物正文与下载字节一致；刷新仍显示完成，390×844 移动布局通过，无 pageerror。服务器模型运行和本机文件执行都是真实进程，模型响应为显式演示。

服务器升级采用已提交源码归档 + 本机构建产物，校验 SHA256，迁移前备份；Web/Worker 仍由 systemd 管理，仅 loopback 监听。原账号与数据未清空。实际升级已运行新增编号迁移，后续发布显示无待迁移项。

一次资源观察：服务器总内存 1870 MiB，available 1090 MiB；Web MemoryCurrent 165097472 字节、Worker 205897728 字节；根盘使用 6.5 GB，剩余 31 GB，代码多版本目录合计 582 MB。这些是采样时点，不是峰值、压力测试或生产容量承诺。

## 验收中发现并修复

- SSH 隧道大 JS 文件下载缓慢：服务端预生成 gzip，767302 字节主 JS 压缩为 228381 字节；真实隧道下载并解压核对一致。仍存在 Vite 大 chunk 提示，未据此声称首屏性能达标。
- HTTP 连接重用偶发 reset：Gunicorn keep-alive 调为 15 秒，浏览器验收 GET 查询允许网络重试；POST 不盲目重放。
- 本机速度限定的轮询次数不足：验收改为 300 秒总时限并输出实际阶段；未放宽业务关卡。
- 中文请求使用 UTF-8 JSON，避免 ASCII 转义放大而使合法文本回执超过请求限制。

## 未验证与限制

- 未调用真实付费模型；演示模型跑真实图与工具，但不代表真实模型任务成功率。
- 真实客户端实测 macOS；Linux / WSL2 实机尚未验证，原生 Windows 明确不支持。
- 当前单主机 checkpoint、单服务器低并发、SSH 本人验证；尚无公网 HTTPS、公开注册、配额、登录限速和正式备份恢复演练。
- 本版无任意 Shell、浏览器自动化、图片本地工具、目录递归扫描或覆盖写入。
- `uncertain` 需要人工核实，不承诺 exactly-once 或透明续跑；撤销不能回滚已开始的写入。
- 新 UI 最近任务最多 100 项，过程显示最近 100 条事件，完整事件仍在数据库/旧接口；未实现历史分页界面。
- 无独立前台需求对话 Agent；任务创建后用户显式启动，主 Agent 在 Attempt 内编排。没有伪造自动接单能力。
- Graph 单次调用步数与活跃执行超时仍受控，但跨审批/设备等待的累计 token 成本预算尚未实现。
