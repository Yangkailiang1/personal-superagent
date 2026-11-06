# V0.5 核心实现

## 文件入口

- intake/models.py、schema.py：会话、调用、确认快照和 Pydantic 草稿。
- intake/services.py：send/edit/confirm/project_result 业务事务。
- intake/agent.py：真实/演示 DeepAgents 接待图，工具双层白名单。
- intake/views.py：Session + CSRF + owner 的 JSON 接口。
- model_status.py 与 model_check 命令：无请求配置状态、显式真实工具验证。
- web/board.py：六列映射、筛选、分页、模型状态。
- frontend/src/Board.tsx、Intake.tsx、History.tsx：看板、会话草稿、来源与事件历史。

## 一条需求如何流动

1. POST conversations 创建空会话。send 锁会话、检查版本和活动调用，持久化消息、输入快照和内部 Attempt。
2. 原 Worker 领取。child 按 snapshot.kind 分流到接待图，环境仍只传模型所需变量。图中的 update_draft 仅更新内存结果。
3. Worker 收到 JSONL result，原 complete 验证领取凭证、租约与取消。finish_locked 在同一业务事务调用 project_result，验证 JSON/Pydantic 与起始版本后写草稿和回复。
4. 用户编辑增加版本；confirm 检查未决问题和假设，原子写确认快照与 pending Task，冻结来源 Turn ID。
5. 用户普通启动进入原工作图，原审批、本地操作和产物不变。

输入限制：消息 1—6000 字；会话历史正文累计 24000 字，超限要求新会话，不静默裁剪；草稿条目最多十二项、每项最多八百字，任务正文最多一万字。接待图 recursion_limit=16，子进程结果超过三万字符拒绝，避免协议截断。原 Worker 默认三十分钟执行超时继续适用。没有累计 token 预算或价格估算。

## API

- `/api/intake/conversations/` GET 列表，POST 新建。
- `/api/intake/conversation/?id=...` GET 会话、草稿、调用状态、确认记录。
- `/api/intake/send/` POST id、version、request_key、text、mode。
- `/api/intake/edit/` POST id、version、draft。
- `/api/intake/confirm/` POST id、version、request_key、accept_assumptions，可选 grant_id/source_path。
- `/api/intake/cancel/` POST id、turn_id，只取消所属会话本轮调用。
- `/api/dashboard/` GET q、mode、column、history、page，返回列定义、当前页、总数及模型非敏感状态。
- 原 `/api/task/` 增加来源确认、历史 Attempt 列表；原 events 接口按 after 游标读取，每页最多二百条。

变更接口继续 CSRF；资源查询按 owner。版本/活动冲突返回 409，非法参数 400，其他用户资源 404。没有模型确认/启动/集成工具。

## 关键不变量

内部 Task 只复用执行基础设施，不进入正式任务入口；确认才产生业务任务。模型不能批准自己。取消后即使子进程迟到返回也不投影草稿。配置变化使旧验证状态失效；模型/接口变化使排队接待调用拒绝旧输入配置。旧图不做代码格式化，保留 checkpoint 指纹。
