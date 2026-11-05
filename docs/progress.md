# 进度与验收记录

最后更新：2026-11-05（Asia/Shanghai）

## 当前状态

用户已说明理解旧 Workbench 的基础 Agent 内容，并明确要求推进。跳过重复基础练习，直接进入第二课：Django 登录、业务任务和 owner 隔离。旧项目能力不自动计作本项目已实现；第二课用户练习仍待验收。

| 阶段 | 状态 | 证据 / 下一步 |
| --- | --- | --- |
| 记录目录、总纲、路线图、决策 | 已建立 | 本目录 docs 文档 |
| 第一课：环境与最小单 Agent | 参考实现已验证 | 离线执行图调用工具得到 42；4 项测试通过 |
| 第一课：用户修改与解释 | 按用户反馈跳过重复练习 | 用户已理解旧 Workbench 的 Agent 基础 |
| 工具错误、超时、流式、持久化、取消、审批 | 未实现 | 后续单 Agent 课程 |
| 第二课：Django 登录与归属任务 | 参考实现已加入 | 见第二课讲义；用户练习待验收 |
| PostgreSQL / 独立 Worker | 配置与驱动已加入 / Worker 未实现 | 下一课实测数据库事务、领取及执行；尚未验证 PostgreSQL |
| 多 Agent、用户本地客户端 | 未实现 | 按路线图推进 |
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
