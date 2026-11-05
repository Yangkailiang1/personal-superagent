# V0.2 验证报告

验证日期：2026-11-05，macOS Apple Silicon。本报告描述本机开发验收，不代表公网生产或真实模型成功率。

## 实际执行环境

- Python 3.12.13，独立 uv 环境；Django 5.2.19、DeepAgents 0.7.30、LangGraph 1.2.18。
- psycopg 3.3.8、psutil 7.2.2；依赖完整锁定于 uv.lock。
- Docker 29.9.2，专用 PostgreSQL 16 Alpine 容器、独立账号/数据库与卷；测试自动创建并销毁 `test_personal_superagent`。
- Playwright 1.64.1 驱动本机缓存的 Chromium 实际执行，无付费模型调用。

## 自动测试结果

| 命令 | 实际结果 |
| --- | --- |
| `uv run --env-file .env.dev --locked manage.py migrate` | 从空 PostgreSQL 库应用已有与新增编号迁移成功 |
| `uv run --env-file .env.dev --locked manage.py check` | 无系统检查问题 |
| `uv run --env-file .env.dev --locked manage.py makemigrations --check --dry-run` | 无遗漏迁移 |
| `uv run --env-file .env.dev --locked manage.py test personal_superagent.tasks personal_superagent.execution --noinput` | **24 passed**，8.650 秒 |
| `uv run --locked pytest -q` | **7 passed**，1.29 秒 |
| Ruff `--select F` 检查新增执行模块、脚本和新测试 | 通过 |
| `git diff --check` | 通过 |

实际覆盖：

- 登录/退出、匿名拦截、owner/status 伪造、跨用户列表/详情/执行/事件隔离、CSRF、表单长度和 HTML 转义。
- 相同幂等键重复及并发启动、不同键活动冲突、数据库活动唯一约束。
- 多个独立数据库连接并发领取，无重复任务，全局额度最多 2。
- 真正运行两个 DeepAgents 子进程，调用 text_statistics 工具、保存最终结果，且两个执行时间区间实际重叠。
- 事件序号连续、游标续读、快照终态与最终事件一致。
- 过期心跳不能复活，迟到事件与结果被隔离；旧进程未停止时禁止重试，错误 token 不释放归属。
- 取消与成功竞争时已提交取消优先；运行取消和超时会终止真实 OS 子进程。
- 真正 SIGKILL 一个 Worker，启动新的 Worker，旧任务标中断、确认子进程退出，不自动重新执行。
- PID 复用身份判断、远端主机不擅自确认停止。
- 真实模式缺少模型配置时失败，不降级演示；白名单以外的原生文件、Shell、委派工具被执行边界拦截。

超时和运行取消测试用真实睡眠子进程作为固定协议夹具，保证时序可重复；正常成功链路则运行真实 DeepAgents 图。二者均不是付费模型验证。

SQLite 教学配置也执行过回归：基础接口通过、PostgreSQL 专项明确跳过，Worker 拒绝 SQLite。正式领取验收以本报告 PostgreSQL 结果为准。

## 真实浏览器验收

内置浏览器控制连接连续超时，改用 Playwright + 本机 Chromium，启动真实 Django HTTP 服务和独立 Worker，不用 Django Client 代替浏览器。

实际通过流程：

1. 密码登录，创建任务，选择离线模式启动。
2. 排队时刷新，仍读到同一执行；关闭任务页面。
3. 独立 Worker 完成后重新打开页面，显示成功与离线结果。
4. 展开过程，显示真实工具结束事件。
5. 新建另一任务，取消排队；创建新 Attempt 重试。
6. 保持页面打开，轮询自动更新为成功；历史保留取消与成功两次记录。
7. 通过 POST 退出登录。

脚本为 `scripts/browser_smoke.py`，截图在本地忽略目录 `.artifacts/v02-success.png`、`.artifacts/v02-retry.png`，已目视检查布局。临时浏览器验收账号及其任务在验收后删除，没有留下默认密码。

## 实测发现并修复

初始版本用后台 daemon 线程阻塞 `sys.stdin.buffer.read()` 监控父进程，子进程已输出最终结果，但解释器退出抢不到输入缓冲区锁而崩溃。修复为 `os.read(fd, 1)` 后，重复执行并行与恢复测试均通过。未将结果已出现视为进程正常完成的替代证据。

## 未验证与已知限制

- 未调用付费供应商，未测真实模型质量、费用、模型超时期间的供应商侧计费或供应商工具兼容性。
- 没有 checkpoint / 中途恢复，没有审批、子 Agent 编排或本地设备协议。
- 没有任意 Shell / 用户代码执行，没有 OS 沙箱；不能把工作进程分离当作安全沙箱。
- 未部署公网，未做容量/长时间压力测试、2 核 2 GB 内存测量、TLS、登录限速和备份恢复演练。
- 本版结果为文本，最多保存 32000 字符；不是 token 实时流、Markdown 富文本或文件产物系统。
- 远端或无法确认身份的旧进程保守保持占用，不提供强制解锁按钮。恢复需要在原主机核验。

下一版按 V0.3 补齐多 Agent、计划、审批与 checkpoint，不把上述缺失能力描述为已完成。
