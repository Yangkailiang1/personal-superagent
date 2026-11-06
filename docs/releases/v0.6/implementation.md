# V0.6 核心代码与数据流

## 模块

- collaboration：schema / models / questions / plans / routing 分别负责协议、持久化、问答、发布事务和路由；jobs 是受限路由/知识/巡检图。
- workflow_v06：新工作图、原生审批、文件工具、持久化额度。原 workflow 和 workflow_v03 未改，execution/versions 在图目录外做新版本分流，避免改变 V0.4 目录哈希。
- client/worker_agent：本机模型配置、能力清单与独立进程监督；job_transport 管理心跳、事件 outbox 和图片/结果投递。
- collaboration/device_jobs：设备能力、领取、心跳、事件与回执；assets 验证和受保护图片接口；toolkit 装配搜索/生图/MCP。
- knowledge/services：来源、整理快照、建议、修订确认、查询和巡检调度。
- MainChat / RouteTarget / Knowledge：主对话、执行目标调整、知识与巡检界面；Dashboard 继续使用后端事实。

## 关键事务

`publish` 锁 Conversation，检查版本/幂等、问题/假设及资源，原子创建 Release、Task 与依赖。模型不持有调用它的工具。

`dispatch_pending` 锁 pending 任务，依赖满足才生成路由 Job；路由结果通过 `project_route` 校验候选并保存负责人，下一个调度周期才 enqueue 正式 Attempt。失败留在待处理，不无限重试。用户可在任务尚未执行时调整目标；冻结后要通过新 Plan 修订改变输入。

`claim_next` 同时支持云端和设备，使用同一额度锁和活动计数。设备 claim 返回固定 JSON 协议，不返回代码或命令；模型配置、Plan 和目录授权在快照冻结。`control` 校验设备归属和领取 token，事件及游标同事务递增，回执按 Attempt/token/digest 幂等。

`complete` 在原凭证/租约/取消规则下投影 checkpoint、审批、文档与图片。设备只报告原 checkpoint，不能凭一个“成功”字符串跳过云端匹配审批的文档校验。设备结果不是独立测试结论。

`approve` 对 Proposal 加锁，按每页 base revision 检查冲突；所有页面修订和日志同事务发布，重复确认不重复新增。Source 不提供改写接口。

## 接口

- 主对话沿用 `/api/intake/`，新增 answer、publish；answer 使用 question_id、choice=0/1/2/3，自定义回答在 custom 中，保留 version/request_key。publish 使用冻结 Plan 版本和 policy。
- `/api/collaboration/agents/`、tools 查询能力；route 调整尚未执行任务；ack-stop 是明确的人工停止确认。
- `/api/device/agent-hello/`、agent-claim、agent-control 使用设备 Bearer，旧文件协议兼容。control 动作包括 heartbeat/event/image/result，所有结果关联当前领取。
- `/api/images/{id}/` 预览，`?download=1` 下载，均 owner 保护。
- `/api/collaboration/wiki/`、source、propose、approve、query、schedule 管理知识与巡检，浏览器变更继续 CSRF。

## 限额

Plan 默认每任务模型请求 24（含路由）、最多 48；生图默认 0，最多 2；超时最多 1800 秒。角色模型单并发。搜索每 Attempt 最多 3 次、MCP 最多 8 次；生图失败也已消耗尝试额度，不自动重复消费。验证模型的两次请求是用户显式操作，不计入任务额度。

本机 Key 的最终账单由用户供应商决定，云端只能限制本系统下发的执行，不能声称限制用户在别处使用同一 Key。
