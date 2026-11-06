# V0.7 核心代码与数据流

## 云端入口

- `happier/models.py`：Repository、ExternalRun、Permission。AgentProfile 和 Attempt 新增 executor_kind，默认 deepagents，旧数据不变。
- `happier/services.py`：hello 同步公开仓库能力；eligible 检查设备、版本、基线与范围；enqueue 冻结本次输入；claim 复用全局 advisory lock；control 处理心跳、递增事件和结果；decide 仅写用户决定；snapshot 只投影展示。
- `happier/policy.py`：Pydantic 校验仓库策略和交付报告，限制路径、命令形态及报告尺寸。

锁顺序统一 Task → Attempt → ExternalRun/Permission。批准请求以版本和 request_key 幂等；每个外部工具请求唯一键为 run + request_id。重复事件必须内容一致。决策先记录，客户端执行并回传 permission_applied 后才显示生效。

发布调用 collaboration.plans.publish，保持现有修订/依赖/原子 Task 创建；coder 额外要求明确仓库。execution.lifecycle.enqueue 分流 Happier，避免用云端 OpenAI 配置校验本机 Claude。claims 按执行器过滤，共享全局额度。旧图文件没有为本版增加逻辑。

结果只能由当前 token/instance 提交。租约过期或取消后，回执只能确认进程停止，不能把旧成功写回。缺少配置的检查、非零退出码、范围违规均不能成功。云端保存的是本机证据，并非独立验证。

## 本机入口

- `client/happier/repositories.py`：登记绝对路径，只上传公开 manifest；按完整提交创建 worktree；关闭 Git hooks、外部 diff/textconv；回收跟踪和未跟踪文件，包括新建文件内容。
- `client/happier/ledger.py`：SQLite 保存启动意图、进程身份、顺序事件、上传游标、最终结果和回执。
- `client/happier/worker.py`：驱动 Node、周期续租、处理决定、执行预授权检查、收集结果；中断只核查/收尾，不重放任务。
- `executor/src/upstream/backend.ts`：由 Happier backend 适配，调用固定 Claude Agent SDK；通过 init 获取 session ID，只以 result 判断成功；EOF/idle 不等于完成。
- `executor/src/policy.ts`：每个工具执行前判 allow/deny/ask；`permissions.ts` 绑定审批 ID 和不可变工具参数，防止缓存决定被用到新命令；`main.ts` 是版本化 JSONL 控制入口，处理 start/inspect/respond/cancel，完成时 collect。

JSONL 每条含 protocol=1，启动参数由本机授权构造。云端没有下发可执行代码、环境变量、CLI 路径或任意参数的入口。凭据使用用户本机 Claude 登录，开发者应在自己的终端配置。

## 接口

设备 POST `/api/device/happier-hello|happier-claim|happier-control/`：沿用 Bearer，仅绑定设备可用。control 携带 id/token/instance/action，事件另外携带 sequence；result 带结构化 report。

浏览器 GET `/api/happier/repositories/` 只列本人设备授权；POST `/api/happier/decide/` 携带 id/version/request_key/decision。任务详情沿用现有 API，新增 executor 和 external，包括审批、基线、策略和报告。

MainChat 可为步骤选择已登记代码仓库；Plan 卡片展示写入范围和检查。全 coder 计划发布为本机 real 执行，演示接待不冒充真实 Claude。混合计划仍需云端真实模型可用。高级编辑可缩小写入范围和检查，服务端拒绝扩大范围。

TaskDetail 展示独立审批卡、差异、文件、检查输出、任务分支以及报告下载。现有 Dashboard 依据同一 Task 状态展示待审批等阶段，不另造状态机。
