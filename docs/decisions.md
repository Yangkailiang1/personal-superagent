# 技术决策记录

## ADR-001：Django + DeepAgents（2026-11-05）

选择 Django 5.2 LTS，利用认证、ORM、迁移和 Admin；DeepAgents / LangGraph 承担 Agent 执行。Flask 可以实现，但本项目需要自行拼装的账号和管理能力更多。Java/Spring 和旧 Harness fork 不再作为本项目主线，原目录保留。

## ADR-002：先单 Agent，再编排

先理解工具 schema、模型请求、ToolMessage、停止条件、checkpoint、取消和审批，再加入子 Agent。第一课不实现所有这些机制，只实现工具循环。多 Agent 不用于掩盖单次执行的不可靠性。

## ADR-003：云端控制、本地执行

云端负责模型和业务任务；用户客户端只执行授权工具。通信协议、资源授权、幂等和离线恢复需要自己实现，不能只替换 DeepAgents Backend 就宣称完成远程连接。

## ADR-004：教学参考与用户练习分开

提供可运行的最小参考，帮助定位环境错误。用户仍需亲手修改、解释和提交验收结果。进度表分别记录参考验证和用户完成情况，不提前建整套服务。

## ADR-005：依赖与状态分阶段

第一课锁定已有可验证的 DeepAgents 0.7.30 基线，使用独立环境；Django 5.2 一起验证可安装性，尚不启用。PostgreSQL 和持久化 checkpointer 在对应课引入。第一课不保存历史，结束进程即丢失内存状态。

参考官方资料：[Django 认证](https://docs.djangoproject.com/en/5.2/topics/auth/)、[Django 支持版本](https://www.djangoproject.com/download/)、[DeepAgents 后端](https://docs.langchain.com/oss/python/deepagents/backends)。实际调用接口以本次锁定并测试的版本为准。

## ADR-006：按已掌握内容推进应用层（2026-11-05）

用户已理解旧 Workbench Agent 实现，因此第二课直接进入 Django 登录、任务与 owner 隔离，暂不重复基础教学。为减少一次引入的概念，采用同源服务端模板、Session、ModelForm，不增加 React、JWT 或通用 API 框架。

默认设置保持 PostgreSQL；另提供显式 `settings_local` 用 SQLite 验证本课登录和查询，不自动回退。它不作为下一课并发领取的依据。未接入 Worker 前任务只处于待执行，页面不调用 Agent，也不提供虚假的运行按钮。
