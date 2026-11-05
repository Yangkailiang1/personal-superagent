# 进度与验收记录

最后更新：2026-11-05（Asia/Shanghai）

## 当前状态

用户已批准逐版完整交付。当前 V0.3 已实现多 Agent、计划、审批和 checkpoint 恢复，并部署服务器供本人经 SSH 隧道验证。下一版 V0.4 本地客户端，再推进 V0.5 多用户邀请内测。旧课程只作参考。

| 阶段 | 状态 | 证据 / 下一步 |
| --- | --- | --- |
| 记录目录、总纲、路线图、决策 | 已建立 | 本目录 docs 文档 |
| 第一课：环境与最小单 Agent | 参考实现已验证 | 离线执行图调用工具得到 42；4 项测试通过 |
| 第一课：用户修改与解释 | 按用户反馈跳过重复练习 | 用户已理解旧 Workbench 的 Agent 基础 |
| 工具/执行事件、超时、取消、结果持久化 | 已实现 | V0.3 补充审批和 checkpoint；无 token 实时流 |
| Django 登录与归属任务 | 已实现并回归 | 无需用户手写练习才能推进 |
| PostgreSQL / 独立 Worker | V0.2 已实现并实测 | 见版本验证报告 |
| 多 Agent、计划、文档审批与恢复 | V0.3 已实现 | 原生 DeepAgents / LangGraph；见本版验证报告 |
| 用户本地客户端 | 未实现 | V0.4 |
| 多用户验证、部署、邀请内测 | 未实现 | 不视为已具备上线能力 |

## 2026-11-05 第一课参考验证

环境：macOS，Python 3.12.13；本项目独立 `.venv`。uv 0.13.6；DeepAgents 0.7.30、LangGraph 1.2.18、langchain-openai 1.7.3、Django 5.2.19，完整解析写入 `uv.lock`。

| 命令 / 验证项 | 实际结果 |
| --- | --- |
| `uv sync --python /Users/yangkailiang/miniforge3/envs/langchain/bin/python3.12` | 独立环境安装成功、生成 lock；仅使用基础解释器，不复用旧项目虚拟环境 |
| `uv run --locked superagent --demo` | 模型请求 add_numbers(17,25) → ToolMessage=42 → 最终回答=42 |
| `uv run --locked pytest -q` | 4 passed；包含真实图工具关联、两类非法参数、配置缺失不降级 |
| 真实供应商模型 | 未调用；未消耗付费模型或生图额度 |
| Django 服务 / PostgreSQL | 尚未接入；仅验证 Django 依赖可安装、可读取版本 |

未迁移旧数据库，未读取旧 `.env`，未改动旧 Workbench 或 Harness 代码。新目录处于现有工作区内，未单独初始化 Git 仓库，未提交或暂存根仓库已有修改。

## 后续记录格式

每课补充日期、目标、用户修改文件、运行命令、实际结果、遗留问题和下一步。对无法执行的验证明确写“未验证”，不能以离线模型或单元测试代替真实部署结果。

## 2026-11-05 第二课：Django 登录、任务与归属

依据用户反馈提前进入应用层，新增讲义 `lessons/02-django-tasks.md`。参考实现增加 Django 项目配置、内置 Session 登录与 POST 退出、任务模型与初始迁移、ModelForm、业务服务、列表/详情模板和测试。owner 永远来自登录用户，状态不接受浏览器赋值。

- `manage.py check --settings=personal_superagent.web.settings_local`：无问题。
- `manage.py test personal_superagent.tasks --settings=personal_superagent.web.settings_local`：7 项通过。覆盖匿名拦截、真实密码登录/退出、owner/status 伪造、跨用户列表与详情、非法表单、CSRF 拒绝与正常提交、HTML 转义。
- `manage.py makemigrations --check --dry-run --settings=personal_superagent.web.settings_local`：无遗漏迁移。
- 独立安装并锁定 psycopg 3.3.8；未连接 PostgreSQL，不声称已经验证并发和事务领取。
- 第一课发现用户已将离线参数改成 8 + 13 并新增乘法工具；保留用户代码，只同步旧测试和说明为预期 21。乘法工具的 Agent 注册和调用练习未代写。
- 同步后 `uv run --locked pytest -q`：4 项通过；离线 CLI 真实工具调用返回 21。
- 没有运行付费模型，没有为用户创建默认密码，没有启动常驻服务器。浏览器双账号手动验收待用户完成；自动验证走真实 Django 请求栈。

下一课：先建立独立 PostgreSQL 开发库，再实现任务与 Attempt、原子领取、独立 Worker、执行结果及重启中断处理。暂不引入 Redis/Celery。用户先完成第二课的迁移练习与双账号隔离验收。

## 2026-11-05 V0.2：改为逐版交付

上面的课程记录是历史状态。用户随后授权逐版开发，本版不再等待手写练习。

- 建立独立 Git 仓库，origin 为 `https://github.com/Yangkailiang1/personal-superagent.git`，已推送 main 的初始内容；V0.2 使用 `codex/reliable-task-execution` 开发分支。
- 新建专用 PostgreSQL 16 容器与持久卷，生成独立 `.env.dev`，保留既有 `.env` 和 SQLite 文件，不迁移旧库。
- 新增 Task 状态迁移、Attempt / RunEvent、幂等启动、数据库领取、全局额度、领取凭证、心跳、子进程监督、取消、超时、中断核验和显式重试。
- 完成 Chromium 真实页面流程：登录、创建、启动、刷新、关闭页面后继续完成、过程事件、取消、重试、轮询更新、退出。
- 初次实测暴露 stdin 后台缓冲锁导致解释器退出崩溃，已改用文件描述符读取并通过回归。
- 交付 [本版完整文档](releases/README.md)；测试数量、命令和未验证项以 [验证报告](releases/v0.2/verification.md) 为准。

下一版 V0.3：主 Agent 与受限子 Agent、计划和子任务关联、人工审批、checkpoint 和上下文恢复。仍不提前接入任意宿主 Shell 或设备工具。

## 2026-11-05 V0.3：协作与本人验证部署

以上 V0.2 的“下一版”记录为历史状态。本次完成：

- 保护本机 `.server`：Git 忽略、权限 0600，固定 SSH 主机指纹，没有输出密码。
- 主 Agent 计划与委派，writer / reviewer 使用独立上下文和角色白名单，每 Attempt 一个模型并发槽。
- 原生 HITL 文档审批，等待时退出子进程并释放额度；恢复同一 Attempt，重试另建记录。
- 新增审批、产物与子任务表；每 Attempt 独立 SQLite checkpoint，版本/源码/模型兼容性检查，缺失或损坏不从头执行。
- 页面分别展示计划、子 Agent、审批、Markdown 回答和受保护下载。
- 服务器独立 Python 3.12 / uv / Docker；只 PostgreSQL 使用容器，Web/Worker 由 systemd 管理，仅监听 loopback，一并发、演示模式。
- 最终本地回归 32 项 Django/PostgreSQL + 13 项 Agent 测试通过；本地及远程 Chromium 全流程通过，远程包含待审批时重启服务再批准下载。
- 约 30 秒采样应用 RSS 合计最大 534.2 MiB，不视为长期压力/容量测试。详见 [V0.3 验证报告](releases/v0.3/verification.md)。
- 已修复待审批页面重复刷新、SSH stdin 被 Docker 读取导致发布步骤丢失、并行文档状态覆盖和不完整快照误标成功等问题。

没有付费模型调用；临时验收账号清理，正式账号由用户在安全终端设置。下一版 V0.4：本地客户端主动连接、账号绑定、目录/工具授权、操作 ID 幂等、离线等待与重连。
