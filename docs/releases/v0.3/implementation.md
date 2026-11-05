# V0.3 实现阅读指南

## 代码入口

| 模块 | 职责 |
| --- | --- |
| `workflow/factory.py` | 创建 DeepAgents 图、两个角色、TodoListMiddleware、原生 interrupt_on 与自定义状态 |
| `workflow/policy.py` | 模型 schema 过滤、执行白名单、父调用关联、单 Attempt 模型并发槽 |
| `workflow/demo.py` | 固定响应，仍经过真实工具、子 Agent、审批、checkpoint |
| `workflow/tools.py` | Pydantic 校验的保存文档工具，只更新图状态 |
| `workflow/checkpoints.py` | 路径、兼容指纹、SQLite 生命周期、状态快照、原生恢复 |
| `execution/projections.py` | 计划/子任务/审批/产物幂等投影，不运行模型 |
| `execution/approvals.py` | 用户决定、版本检查、恢复状态与排队 |
| `execution/worker.py`、`child.py` | 扩展 JSONL 协议传递快照，保持 V0.2 监督与凭证约束 |
| `execution/templatetags/markdown.py` | MarkdownIt 禁用 HTML 的单一渲染入口 |
| `scripts/deploy/` | 固定主机指纹的 SSH、环境准备、提交归档发布、隧道和本人建号 |

## 关键函数与调用链

`enqueue()` 冻结输入和工作流配置 → Worker `claim_next()` 原子领取 → `spawn()` 传入 Attempt UUID、动作、checkpoint 目录、审批决定 → 子进程 `run_workflow()` 创建图 → `graph.stream(..., subgraphs=True)` → 导出图快照 → Worker 回收进程 → `complete(..., snapshot=...)`。

`run_workflow(payload, emit) -> dict` 区分 start、resume、continue。start 有现成状态时拒绝覆盖；resume 用 `Command(resume={interrupt_id: decisions})`；continue 用 None 从已保存状态继续。恢复不把历史展示卡片重新拼为模型输入。

`snapshot(graph, config)` 用原生 `get_state` 读取 todos、documents、待审批动作和根图消息；按工具 ID 重建委派。它既用于正常退出，也用于事故后补齐业务投影。

`apply_snapshot_locked(attempt, data)` 必须在 Task/Attempt 行锁内调用：先保存 checkpoint ID 和计划，再按稳定 ID 新建审批、验证并创建产物、重建子任务。所有写入同一事务，失败则回滚。文档内容必须与已批准动作参数完全匹配。

`decide(user, task_id, attempt_id, approval_id, expected_version, request_key, decision)` 检查 owner、执行状态、进程停止和审批版本。相同请求返回原决定；冲突不覆盖。全部当前动作完成后只排队，不在 HTTP 中执行模型。

`resume(user, task_id, attempt_id)` 只允许已停止且未取消的 interrupted Attempt。在原主机检查配置和 checkpoint，恢复遗漏审批或排队 continue。缺少 checkpoint 的历史执行明确报错。

## 数据和接口变化

新增编号迁移：扩展 Task/Attempt 状态与活动约束；Attempt 增加版本、动作、计划和 checkpoint ID；新增 Approval、Artifact、SubTask。既有 pending 任务不会自动入队，V0.2 Attempt 的 workflow_version 为空。

新增接口均沿用 Session、CSRF、owner 校验：

- `POST /tasks/{tid}/attempts/{aid}/approvals/{approval_id}/`：version、request_key、decision=approve/reject；过期/冲突 409。
- `POST /tasks/{tid}/attempts/{aid}/resume/`：恢复中断 Attempt，重复的已排队恢复为幂等；不兼容 409。
- `GET /tasks/{tid}/attempts/{aid}/artifacts/{id}/`：预览；`?download=1` 返回 Markdown 附件。
- 事件接口增加 plan、subtasks、服务端渲染的 result_html；仍保留原字段。

Markdown 原始 HTML 禁用，危险链接由解析器拒绝。JS 只将服务器的安全 result_html 放入正文，过程文本使用 textContent。审批区域直接显示，不藏在执行过程折叠内。

## 扩展点与边界

新增角色时在 factory 注册模型、描述、提示词与工具白名单；同时更新 policy 和工作流版本，再补权限与事件测试。不能只在 YAML/提示词中写“禁止 Shell”就算权限控制。

新增产物类型时先定义 schema、审批参数、图内状态和幂等投影，再增加下载入口。不能让子进程直接拿业务数据库密码随意写表。

子进程 stdout 单行上限提高至 256 KiB，以容纳受限文档快照；正文单份最多 12000 字符，每次执行最多两份。总图步数上限 48，每段活跃执行默认超时 30 分钟；审批等待不占用该段计时。此处尚未实现供应商 token 成本上限。
