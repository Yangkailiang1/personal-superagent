# V0.4 核心代码与调用关系

## 模块划分

| 模块 | 职责 |
| --- | --- |
| `devices/models.py`、`auth.py` | 设备、绑定码、目录授权、本地操作、哈希凭证 |
| `devices/protocol.py` | 会话替换、授权同步、原子领取、开始前校验、幂等回执、未知结果处理 |
| `devices/workflow.py` | 冻结任务范围、将 interrupt 投影为操作、所有关卡完成后恢复 |
| `client/config.py`、`cli.py` | 本机私密配置、绑定、grant/revoke、启动；不会把绝对路径放入 manifest |
| `client/agent.py`、`ledger.py` | 主动轮询、进程锁、工具超时、started/completed 账本、回执重发 |
| `client/files.py`、`tool_process.py` | FD 约束的真实文件操作，固定工具子进程，无 Shell |
| `workflow/local_tools.py` | 本地工具 schema 和原生 interrupt，不持有设备或数据库凭证 |
| `workflow/versions.py`、`workflow_v03` | V0.4 / 冻结 V0.3 执行与恢复选择 |
| `web/dashboard.py` | 同源 SPA 资源与 owner 保护的任务/设备 API |
| `frontend/src` | 页面、assistant-ui 适配、任务详情、设备页、样式与 HTTP 客户端 |

## 读取本机文件怎样执行

1. `enqueue()` 调用 `scope_for(task)`，验证归属与授权，把设备/目录/工具版本冻结进 Attempt，不包含绝对路径。
2. `build_workflow(local_scope=...)` 只给主 Agent 暴露已授权工具；工具 `local_read_text` 调用 `interrupt()`，图暂停并持久化。
3. `snapshot()` 导出 local_requests；Worker 回收子进程后，`sync_requests_locked()` 按工具 ID 创建 LocalOperation，Task/Attempt 转为 waiting_device。
4. 本机 `run()` 主动 connect/poll。服务端锁 Device 和操作，生成独立领取凭证，不重复领取 leased/uncertain。
5. 客户端 `execute_operation()` 先记账，再核对本地授权和云端 lease，启动固定 tool_process；`files.execute()` 锚定目录 FD 读取真实 UTF-8 内容。
6. 先持久化结果，再 report。服务端先锁 Task/Attempt 后锁操作，与取消路径一致；相同回执幂等，不接受修改已保存结果。
7. `maybe_resume_locked()` 检查所有关卡完成才排队。Worker 把本地结果按 interrupt_id 合并进 `Command(resume=...)`，工具结果进入原对话，主 Agent 可以将明确材料传给子 Agent。

写入比读取多一层：local_write_text 的 HITL 审批 → 批准 → 本地 interrupt → 执行。云端保存交付文档 save_document 是另一项操作，不能把“保存到云端”误当作“写到电脑”。

## 主要函数契约

- `new_pairing(user) -> code`：返回一次性原文，数据库只保存哈希与到期时间。
- `pair(code, name) -> (device, token)`：事务锁定绑定码，只能消费一次。
- `poll(device_id, session, manifest) -> operation|null`：同步本地声明，但不覆盖云端撤销；锁定并领取一项操作。
- `validate_lease(device, id, lease)`：工具开始前再检查授权版本、任务、取消和租约。
- `report(...)`：幂等接收确定/未知结果；过期但真实已完成的旧回执可凭原领取凭证确认，不能恢复已取消任务。
- `Ledger.begin(operation)`：首次写 started；相同 ID 参数改变拒绝，旧 started 返回 unknown，不执行第二遍。
- `directory(root, components)`：每层 O_NOFOLLOW，验证根设备号和 inode；持有 FD 直至操作结束。
- `write_text`：临时文件写完 fsync 后原子链接为目标，已有文件时报错，绝不覆盖。

## API 与数据变化

新增 Device、Pairing、Grant、LocalOperation 表，Task 可选 local_grant/local_file，新增 waiting_device，并扩展活动唯一约束。使用编号迁移保留旧记录。

设备协议 v1，JSON POST `/api/device/{pair,connect,poll,check,report}/`。除 pair 外需 Bearer，非 connect 操作还校验当前 session。设备 token 不使用浏览器 Cookie，不配置跨域授权。

浏览器同源接口：GET `/api/bootstrap/`、GET `/api/task/?id=...`，POST `/api/create/`、`/api/pairing/`、`/api/revoke/`。变更保留 CSRF，资源查询与授权变更都按 owner 过滤。现有启动/取消/审批/恢复/下载接口复用，不另建任务事实来源。

## 前端构建与发布

React、TypeScript、Vite；assistant-ui 只负责消息/输入交互，应用存储仍来自 Django。Markdown 不启用原始 HTML；日志、过程与审批独立于最终回答。页面 2 秒同步，旧页面请求不会覆盖已切换任务。

推荐 Node 24，依赖由 package-lock 锁定。开发电脑构建静态文件，发布脚本拒绝未提交前端修改；Git 归档附加 frontend/dist，整体 SHA256 校验后上传。服务器不安装 Node，也不运行 Next.js/SSR，仍只有 Gunicorn、Worker 和 PostgreSQL。

V0.3 源码目录不格式化或修改，保持旧 checkpoint 指纹兼容；新版本按版本号选择模块。V0.4 更改图结构仍要更新版本或验证恢复，不以“有 checkpoint”承诺任意跨版本续跑。
