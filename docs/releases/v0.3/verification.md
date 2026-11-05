# V0.3 验证报告

日期：2026-11-05，Asia/Shanghai。区分本地自动测试、服务器真实部署与未验证能力；本次没有付费模型调用。

## 本地自动验证

环境：macOS Apple Silicon，Python 3.12.13；Django 5.2.19、DeepAgents 0.7.30、LangGraph 1.2.18、langgraph-checkpoint-sqlite 3.1.3、MarkdownIt 4.2.0。独立 PostgreSQL 16 容器，测试创建/销毁独立 test 数据库。

| 命令 | 实际结果 |
| --- | --- |
| `uv run --env-file .env.dev --locked manage.py test personal_superagent.tasks personal_superagent.execution --noinput` | **32 passed**，63.282 秒 |
| `uv run --locked pytest -q` | **13 passed**，1.90 秒 |
| `uv run --env-file .env.dev --locked manage.py makemigrations --check --dry-run` | 无遗漏迁移 |
| Ruff F 规则检查新执行/工作流/部署/浏览器脚本 | 通过 |
| `git diff --check` | 通过 |

自动验证覆盖：

- V0.2 原有登录、owner/CSRF、幂等、并发领取、额度、超时、取消、旧 token、租约与真实 Worker 崩溃恢复。
- 主 Agent 调用 writer/reviewer；真实图与工具执行；子任务调用 ID / namespace / 结果关联。
- 原生 interrupt 保存前暂停，无正式产物；批准后恢复同一图，不重复运行两个子 Agent；拒绝不发布。
- 原生一次暂停包含两项保存动作，全部批准后并行更新正确合并成两份文档。
- 审批版本冲突、请求重发幂等、等待释放执行额度、取消关闭审批、跨用户审批/恢复/产物访问拒绝。
- checkpoint 已提交、业务投影丢失后，从原生状态补齐审批和子任务；缺失/损坏/不兼容与旧 V0.2 无 checkpoint 恢复被拒绝。
- 原始 HTML 与 javascript 链接不执行，角色不能调用宿主文件、Shell、未知角色或越权保存。
- 不完整图快照不能被标记为成功。

## 本地真实浏览器

Playwright 1.64.1 + 本机 Chromium，访问真实 Django HTTP 服务，实际启动 Worker 子进程。`scripts/browser_v03.py` 完整通过登录、任务创建、计划/两个角色、审批刷新、批准、Markdown 预览和字节下载、拒绝不发布、取消待审批及退出。

本地截图 `.artifacts/v03-approval.png` 与 `.artifacts/v03-artifact.png` 已检查，产物不提交 Git。演示明确标注固定模型响应，不能冒充真实模型生成质量评测。

## 服务器部署与 SSH 隧道验收

实际服务器：Alibaba Cloud Linux 3，x86_64，2 vCPU、1870 MiB 内存、40 GB 根磁盘。系统 Python 3.6.8 保持不变；独立安装 uv 0.13.7、Python 3.12.16、Docker 26.1.3。应用以 superagent 用户运行，不加入 Docker 用户组。

工作流代码验收提交 `1975fc5`；后续交付补充文档和临时账号清理脚本，不改变已验收图逻辑。

- 实际完成专用空 PostgreSQL 库编号迁移、Gunicorn/systemd Web 与 Worker 启动、健康检查。
- `ss -ltn` 核查新服务仅监听 `127.0.0.1:8000` 与 `127.0.0.1:55432`，没有开放公网网页端口。
- 本机固定主机指纹 SSH 隧道映射 `127.0.0.1:18002 → 服务器 127.0.0.1:8000`，浏览器访问实际服务器页面。
- 临时账号随机生成，密码仅本机忽略文件持有；服务器默认 `ALLOW_REAL_MODE=0`。
- 远程真实流程通过：任务 → 两个子 Agent → 待审批 → **重启 Web 和 Worker** → 同一审批仍存在 → 批准 → 成功 → Markdown 预览与下载；另验证拒绝不发布和取消审批。
- 验收后清理临时账号、关联任务与 checkpoint；正式账号密码由用户安全终端输入，没有默认密码。
- 发布实际校验 Git 归档 SHA256、迁移前数据库 dump 和运行目录归档，切换 current 后检查服务。没有执行数据库回滚或备份恢复演练。

## 资源采样（不是容量压测）

远程浏览器验收期间每 0.5 秒采样一次，共 60 次、约 30 秒：

| 指标 | 实际值与解释 |
| --- | --- |
| 应用进程 RSS 合计采样最大 | **534.2 MiB**；包含共享页重复计数，不是精确物理占用或进程历史峰值 |
| 采样结束应用 RSS 合计 | 377.8 MiB |
| Web cgroup MemoryCurrent | 160817152 字节，约 153.4 MiB |
| Worker cgroup MemoryCurrent | 171130880 字节，约 163.2 MiB |
| PostgreSQL 容器采样结束内存 | 39.71 MiB |
| 系统采样结束可用内存 | 1087 MiB；无 swap |
| 根磁盘 | 6.2 GB 已用、约 32 GB 可用 |

保持一个任务执行并发；没有据此证明双任务真实模型容量、长时间稳定性或生产 SLA。

## 实测发现与修复

1. 待审批也属于活动归属，沿用 V0.2 的前端“活动即运行”会不断刷新；改为明确区分 queued/running 与 waiting_approval，浏览器回归通过。
2. 非自动重载本地服务会缓存模板，验证修复前需要重启服务，不能仅根据源码认定新模板已生效。
3. 通过 SSH stdin 传 bash 脚本时 Docker exec 会读取 stdin，吞掉后续发布步骤；改为上传脚本后执行，并显式切断 dump 的 stdin，真实服务器完整发布通过。
4. 原生并行文档状态需要 reducer 按稳定 ID 合并，避免丢失或冲突；新增两文档原生审批测试。
5. 空/不完整快照不能因为子进程退出码为 0 就判成功；增加业务终态测试。

## 仍未验证或未实现

没有真实供应商调用、质量/成本评测、token 预算、本地设备、任意 Shell、OS 沙箱、多机 checkpoint 恢复、公网 HTTPS/限速/配额或公开注册。没有完成灾备恢复和容量压测。当前是本人 SSH 隧道验证部署，不是公网生产开放。
