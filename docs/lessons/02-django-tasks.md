# 第二课：Django 登录、任务与用户隔离

## 本课目标与路线调整

你已说明旧 Workbench 的基础 Agent 代码都看过并理解，因此不再重复单 Agent 工具循环课程，直接推进应用层。原计划中的流式、审批、取消和恢复后续结合 Worker 验收；这里不因为“读过旧项目”就把新项目对应能力标记为完成。

本课实现：登录 → 新建自己的任务 → 列表与详情 → 退出。先用最简单的 Django 模板，没有独立 React、JWT、REST 框架或多 Agent 调度。任务保存后显示“待执行”，**不会偷偷调用模型，也不会伪造完成状态**。

先建立业务数据与身份边界；下一课才将业务任务交给独立 Worker。这比在网页请求中直接调用 Agent 更容易解释超时、刷新和重启。

## 1. Django 的四个概念

| 概念 | 本课对应 | 意义 |
| --- | --- | --- |
| 项目配置 | `web/` | 数据库、中间件、URL 与模板引擎 |
| 应用 | `tasks/` | 一组任务业务功能；不是操作系统进程 |
| 模型与迁移 | `Task`、`migrations/` | 模型描述数据，迁移记录数据库结构变化 |
| 视图与模板 | `views.py`、`templates/` | 视图处理请求，模板生成 HTML |

登录使用 Django 内置用户、密码哈希和 Session。浏览器持有 Session Cookie，服务端通过它识别用户；CSRF Token 用于保护带 Cookie 的写请求。**登录证明你是谁，owner 过滤决定你能看什么。**

## 2. 本课新增哪些文件

文件均在 `src/personal_superagent/` 下，根目录额外增加 `manage.py`。

| 文件 | 职责与关键函数 |
| --- | --- |
| `web/settings_base.py` | 共用中间件、模板、认证、PostgreSQL 配置 |
| `web/settings.py` | 默认配置，缺少密钥时拒绝启动 |
| `web/settings_local.py` | 显式本地教学配置，使用 SQLite 和 HTTP Cookie |
| `web/urls.py` | 挂载 Django 登录/退出和任务路由 |
| `web/wsgi.py` | WSGI 应用入口；不负责启动后台 Worker |
| `tasks/models.py` | `Task` 的归属、标题、需求、状态和创建时间 |
| `tasks/migrations/0001_initial.py` | 初始建表，提交源码，不手工改数据库 |
| `tasks/forms.py` | `TaskForm` 校验长度、必填，只接收标题和需求 |
| `tasks/services.py` | 创建、列表、详情的业务与归属规则 |
| `tasks/views.py` | HTTP 方法、登录检查、表单校验、渲染或跳转 |
| `tasks/urls.py` | 路径到视图的映射 |
| `tasks/templates/` | 三个简洁页面和共用布局；保留 CSRF 和 HTML 转义 |
| `tasks/tests.py` | 登录、越权、非法输入、CSRF 与输出转义测试 |

没有通用 Repository 基类：当前 ORM 查询很少，放在 services 内更直接。也没有 Admin，避免把全局管理权限误当成用户自己的任务页。

## 3. 先运行本地教学版本

```bash
cd /Users/yangkailiang/Documents/DeepAgents/personal-superagent
uv sync --locked
uv run --locked manage.py migrate --settings=personal_superagent.web.settings_local
uv run --locked manage.py createsuperuser --settings=personal_superagent.web.settings_local
uv run --locked manage.py runserver 127.0.0.1:8001 --settings=personal_superagent.web.settings_local
```

浏览器访问 `http://127.0.0.1:8001/`，会跳到登录页。创建用户时使用自己输入的密码，没有默认账号。`createsuperuser` 只是本课便捷建号方式；页面仍然对超级用户执行 owner 过滤，不提供查看所有任务的后门。

如需第二个普通用户，另一个终端运行：

```bash
uv run --locked manage.py shell --settings=personal_superagent.web.settings_local
```

在交互式 Python 中执行：

```python
from getpass import getpass
from django.contrib.auth import get_user_model
get_user_model().objects.create_user(username="second", password=getpass("新用户密码："))
```

这仅供本地测试；`create_user` 不自动执行表单密码强度校验，因此请自己输入强密码。后续邀请注册会通过正式校验流程建号。

本地数据库为根目录 `lesson.sqlite3`，已加入 gitignore。没有启用 `.env` 自动加载。SQLite 是**显式教学模式**，不是 PostgreSQL 连接失败后的自动回退；后续 Worker 的锁、并发领取与恢复必须改用 PostgreSQL 实测。

## 4. 一次请求怎么走

### GET `/`

Session 中间件恢复会话 → AuthenticationMiddleware 得到 `request.user` → `login_required` 拦截未登录请求 → `list_tasks(user=...)` 先按 owner 过滤 → 模板渲染自己的任务。

### POST `/`

CSRF 中间件校验 → 视图构造 `TaskForm` → `is_valid()` 校验 → `create_task(user, form)` 把登录用户写为 owner → 保存 → 重定向详情。采用“POST 后重定向”避免普通页面刷新再次提交；它不是严格幂等机制，用户重复点击仍可能创建两项任务，后续提交任务时再引入请求键。

为什么不让前端传 owner？因为恶意用户能直接构造请求。表单白名单只含 `title`、`description`，即使传入别人的 ID 或 `status=completed` 也不会采用。

### GET `/tasks/<uuid>/`

`get_task(user, task_id)` 在当前用户的 QuerySet 内查 ID；不存在或他人任务统一返回 404。UUID 降低可猜测性，**真正的隔离来自过滤条件，不是 UUID**。

## 5. 核心函数逐个理解

`list_tasks(*, user) -> QuerySet[Task]`：输入当前登录用户，输出限定归属的延迟查询。视图不应自己写全表查询再在模板中隐藏。

`get_task(*, user, task_id) -> Task`：输入用户与 UUID，输出任务或抛出 Http404。后续的取消、附件下载和事件订阅都要检查同样的归属，不能只保护详情页。

`create_task(*, user, form) -> Task`：输入已通过验证的表单和可信登录用户。`commit=False` 先得到对象，设置 owner 后保存。只有一次数据库写入，本课无需包多表事务；后续“任务 + 运行 + 事件”需要一个原子事务。

`TaskForm`：`ModelForm` 从模型生成字段校验；`max_length` 不仅服务前端输入提示，服务端也执行校验。不要直接把任意 `request.POST` 展开进 ORM。

`task_list()` / `task_detail()`：仅负责 Web 流程。不在这里运行 `build_agent().invoke()`；否则请求长时间占用、关闭页面和超时将混淆业务状态。

## 6. PostgreSQL 路径

目标技术栈保持 PostgreSQL，驱动 `psycopg[binary]` 已加入并锁定。按照 [Django 5.2 数据库文档](https://docs.djangoproject.com/en/5.2/ref/databases/#postgresql-notes)，使用 PostgreSQL 14 以上版本；建议本地新建独立数据库，不连接旧项目库。

准备独立账号及数据库后，在终端设置 `PGDATABASE`、`PGUSER`、`PGPASSWORD`、`PGHOST`、`PGPORT` 和随机 `DJANGO_SECRET_KEY`。变量名见 `.env.example`，不要把真实密码提交或发进聊天。然后去掉 `--settings=...settings_local`：

```bash
uv run --locked manage.py migrate
uv run --locked manage.py createsuperuser
uv run --locked manage.py check
```

默认配置启用安全 Cookie，应用部署应使用 HTTPS。若要在 localhost 的 HTTP 下使用 PostgreSQL，创建自己的本地配置继承 `settings_local`，只把 DATABASES 指回 `settings_base.DATABASES`，并显式选择该配置；不要为方便测试关闭默认配置的安全选项。

本课不安装或启动数据库，不访问已有数据库，也不自动把 SQLite 用户复制到 PostgreSQL。后续一课会统一建立 PostgreSQL 开发环境并真实验证 Worker 事务。

## 7. 测试和你的验收

```bash
uv run --locked manage.py check --settings=personal_superagent.web.settings_local
uv run --locked manage.py test personal_superagent.tasks --settings=personal_superagent.web.settings_local
uv run --locked pytest -q
```

Django 测试创建临时数据库，不清空 `lesson.sqlite3`；pytest 保留第一课回归。`Client` 是真实 Django 请求处理测试，不是浏览器自动化，也不是 PostgreSQL 测试。

请亲手完成：

1. 两个账号各创建一项任务；分别登录，确认列表互不可见。复制 A 的详情地址，用 B 登录访问应为 404。
2. 看浏览器请求里的 Cookie、POST 和 302 重定向，解释 Session 与 CSRF 的区别。
3. 给任务增加一个可选 `expected_output` 字段：改模型 → `makemigrations` → `migrate` → 更新表单与详情 → 加测试。不要直接改数据库表。
4. 解释为什么新任务只停留在“待执行”，以及为什么没有直接从这里调用第一课 Agent。

完成后提供你的代码修改和运行现象，我们按行为验收。下一课连接“任务 → PostgreSQL 原子领取 → 独立 Worker → 执行结果”，之后才加入多 Agent 分派。

安全实现参考：[Django 安全机制](https://docs.djangoproject.com/en/5.2/topics/security/)。内测上线还需要 HTTPS、登录限速、运维配置及全资源隔离测试，本课没有宣称这些已完成。
