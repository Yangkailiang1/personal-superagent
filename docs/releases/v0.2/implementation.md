# V0.2 实现与代码阅读顺序

## 第一条链路：网页启动

从 `tasks/urls.py` → `execution/views.py:start()` → `execution/lifecycle.py:enqueue()` 阅读。

`enqueue(user, task_id, request_key, mode, retry=False) -> Attempt`：用户归属检查、锁任务、幂等查询、状态校验、输入冻结、新建执行、任务入队和事件写入。真实/离线模式随 Attempt 固定。重复键改变模式会报冲突；旧失败请求键仍返回旧记录，重试必须使用新键。

UUID request_key 随详情表单生成，双击和网络重发复用该值；同任务锁和唯一约束确保只创建一次。它不是会话鉴权，也不防另一个新键蓄意启动，后者由活动执行约束与状态机阻止。

## 第二条链路：执行与交付

从 `execution/management/commands/agent_worker.py` → `worker.py:run_worker()` → `claims.py:claim_next()` → `worker.py:spawn()` → `child.py` → `execution/agent.py:run_agent()` 阅读。

| 函数 | 输入 / 输出 | 关键责任 |
| --- | --- | --- |
| `claim_next(worker_id)` | Worker UUID → Attempt 或 None | PostgreSQL 额度锁、skip_locked、领取与事件 |
| `spawn(attempt)` | 已领取执行 → Running 或 None | 独立进程、PID 创建时间登记、传入快照、JSONL 读线程 |
| `run_agent(snapshot, mode, emit)` | 冻结输入、模式、事件回调 → 最终回答 | 真实 DeepAgents 图；业务工具；区分过程与结果 |
| `record_event(id, token, kind, data)` | 当前凭证与事件 → 是否接收 | 验证归属/租约，递增事件序号；不接受过期结果 |
| `complete(id, token, state, result, error)` | 已回收进程结果 → 是否提交 | 凭证栅栏、取消优先、统一终态 |

主进程以 0.2 秒监督循环管理最多配置数量的子进程。stdout 使用有边界的 JSONL 协议，队列最多 100 项，每轮消费最多 100 项，单行最多 64 KB，最终结果保存最多 32000 字符。本版不保存全部 token 流和原始工具参数；只记录活动事件与最终答案。

`child_environment()` 明确选择允许传给子进程的变量。模型 API Key 只通过环境传入，不在命令行、输入快照和事件中保存。`redact()` 对已知秘密做精确替换，是额外防护，不是通用数据脱敏解决方案。

## 第三条链路：取消与恢复

`request_cancel()` 保存请求；Worker 检查后终止并回收实际子进程，`complete()` 再提交终态。运行中的“已申请取消”不能提前伪装成“已停止”。

`expire_leases()` 把过期执行置为中断；`processes.py:reconcile_interrupted()` 在同主机核验进程停止后释放归属，留下一条审计事件。后续重试新建输入快照，旧记录不变。

`child.py:watch_parent()` 用 stdin 的 EOF 识别父 Worker 消失。这里使用 `os.read()`，不能换成后台线程长期占用 `sys.stdin.buffer.read()`：实际验收发现后者会在解释器退出时因缓冲区锁触发 fatal error，造成“已得到答案却异常退出”。

## 第四条链路：页面事件

`events(user, task_id, attempt_id, after)` 验证 owner 后返回状态快照、最多 200 条事件、cursor 和 has_more。事件限定到本次快照的 event_seq，下一轮再读后续事件。响应禁用缓存。

任务详情用 DOM `textContent` 更新内容，不把模型输出拼成 HTML。事件与结果分别展示；轮询断开只提示重试，不发取消。终态刷新操作区域；旧进程由未确认转成已停止后，也刷新以显示重试入口。

## 本版接口

| 方法与路径 | 输入 | 行为 |
| --- | --- | --- |
| `POST /tasks/{id}/start/` | 表单 request_key、mode=demo/real、action=start/retry | 创建或返回 Attempt，成功 302；格式错误 400、状态冲突 409 |
| `POST /tasks/{id}/attempts/{aid}/cancel/` | CSRF | 取消排队或申请停止运行；幂等，成功 302 |
| `GET /tasks/{id}/attempts/{aid}/events/?after=N` | 非负游标 | 状态、结果、错误、有序事件、cursor、has_more |

未登录按现有网页登录跳转；越权返回 404。没有新增公开注册、无鉴权 API 或跨域配置。

## 数据兼容

编号迁移 `tasks/0002` 扩展状态，`execution/0001` 新建执行和事件表。已有 pending 任务仍是待启动，不自动排队。保留旧 SQLite 文件；PostgreSQL 是新的独立开发库，没有自动迁移账号或历史。

第一课 `agent.py`、模型和 CLI 保留；业务执行器在 `execution/agent.py` 单独组装，不把教学固定加法提示词用于真实任务。V0.3 会在此基础上增加 checkpoint、受限角色与审批，而不是堆进 Django 视图。
