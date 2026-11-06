# 个人多 Agent 工作台技术架构

## 控制面与执行面

Django + PostgreSQL 保存用户、需求会话、Plan 修订、任务、Attempt、审批、事件和知识来源；独立 Worker 领取队列，网页关闭不终止任务。

```
主对话 Agent → 用户发布 Plan → 依赖队列 / 能力路由
                                    ├─ 云端 DeepAgents：研究、整理、检查
                                    └─ 已绑定设备：Claude / Blender MCP
```

DeepAgents 负责原生工具循环、规划和子 Agent 委派，LangGraph checkpoint 负责需要审批的图恢复；业务任务和执行状态不混为一套 checkpoint。

## 多 Agent 与资源路由

主对话 Agent 制订和修改计划；研究任务由云端主管实际委派研究子 Agent 调用搜索；路由器依据用户归属、工具与能力授权、在线状态、历史职责和额度选择工作 Agent。建模步骤声明 `blender.modeling`，不要求服务器安装 Blender。设备离线或能力缺失时等待，不伪装执行。

已发布输入按 Attempt 冻结，失败重试生成新 Attempt。PostgreSQL 行锁、领取凭证和最多两个活动执行控制并发；过期结果不能复活终态。未确认旧进程停止前不重派副作用任务。

## 本机执行器

保留原文件客户端和 DeepAgents 执行器；Happier 派生 TypeScript backend 使用固定 Claude Agent SDK，由 Python supervisor 管设备通信、心跳、进程和本机账本。CC Switch 只读取认证、接口和模型字段，不启用用户 hooks 或其他插件。

代码任务在独立 Git worktree 中执行。Blender 任务使用专用输出目录及独立 factory-startup GUI 进程，加载用户已装 addon。受限 MCP facade 将结构化几何、材质、灯光和导出请求转换为固定 Blender 程序；不向模型暴露任意宿主 Python/Shell。

## 文件与权限

Task、Attempt、设备、审批和文件追踪均检查 owner。浏览器变更操作使用 Session/CSRF，设备使用独立可撤销 Bearer 凭证。模型凭据只留在其执行位置。

Blender 模型、场景参数及渲染图留在执行设备。云端只存文件 ID、任务与 Attempt、设备、授权标识、相对路径、媒体类型、大小、校验值和可用状态。云端不提供这类文件上传接口；用户可请求在对应设备打开。

本机模型服务可能处理建模上下文；这与工作台存储分别告知。worktree 和目录检查不是安全沙箱；受管进程退出也不等于外部服务副作用已回滚。

## 知识与部署

知识库以用户选定的材料和带来源修订为依据，模型只提出整理建议，用户确认后写入新修订。巡检默认关闭。

当前单服务器部署使用 Gunicorn、systemd 与独立 PostgreSQL，网页经 SSH 隧道访问。发布前备份数据、执行编号迁移、按提交切换代码。真实模型、真实设备与固定协议测试分别记录，不以模拟结果替代验收。
