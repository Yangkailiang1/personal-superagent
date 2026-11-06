# V0.7 架构：本机 Claude 执行器

## 解决的问题

主对话、Plan、Task、路由和知识库继续是云端业务层。本版引入 `HappierExecutor`，借鉴并抽取 Happier 的 Claude SDK backend 生命周期，让已经绑定的电脑执行代码任务。无需部署 Happier 服务，也不兼容其账号、加密或设备同步协议。

```
Django / Plan 发布 → Task → Attempt（executor=happier）
                         ↓ PostgreSQL 原子领取
本机 Python supervisor → TypeScript HappierExecutor → Claude Agent SDK / CLI
      ↑ 本地 SQLite 账本      ↓ 权限回调 / session init / result
      └──── HTTPS/SSH 隧道 → 事件、审批、差异、检查证据 → Dashboard
```

保留 Python 控制设备，是因为它已经实现设备令牌和领取协议；保留一小块 TypeScript，是为了直接适配上游执行层，而不将其复杂协议重写一遍。底层 query 使用固定官方 SDK 0.2.123；不是把完整 Happier CLI 搬过来。复用详情见 executor/UPSTREAM.md。

## 状态与唯一事实

Task 是业务状态，Attempt 是一次冻结输入，ExternalRun 保存本次本机运行实例与回执。Claude session ID 不充当 Task ID，也不充当领取凭证。知识库不直接读取外部会话。

发布仍由用户接口完成。coder Step 必须选择明确设备 Agent、Repository、版本和提交；用户明确指定的执行目标不再额外调用云端路由模型。DeepAgents 执行器保持原有路径；普通客户端与 Happier 客户端不能互相领取任务。

`queued → running → waiting_approval → running → succeeded/failed`。取消、失联、超时可能进入 cancelled/interrupted；无法证实停止前保持 process_stopped=false，阻止重试与超额并发。等待审批也保留执行额度：原生工具请求虽暂停，尚不能证明整个运行没有其他活动。全局上限仍为两个。

## 权限与信任

owner 从 Device 继承；所有浏览器操作使用 Session/CSRF，设备使用 Bearer。Repository 的绝对路径与 Claude 登录凭据只在本机。本机重新检查授权和仓库 inode，云端不能给出任意路径或启动参数。

PreToolUse 拦截每个工具；不能只依赖供应商需要询问时才触发的 canUseTool。文件工具只处理 worktree，写入还需匹配冻结范围；敏感路径与符号链接拒绝。Grep 限单个安全文件，先 Glob 后 Read/Grep，不允许递归检索绕过敏感文件限制。

命令自动执行采用完整白名单：少量固定只读命令、用户批准的测试/构建命令。未知命令、复杂 Shell 和危险操作均走网页逐项审批；不提供绕过权限模式。后台命令和嵌套 Agent 工具关闭。仓库 hooks、插件和 MCP 不自动载入。

worktree 共用 Git 元数据，只保护工作目录，不是安全沙箱。经批准的 Shell 命令仍能访问宿主机其他资源。不要给不可信用户提供此执行器，也不要把“预授权测试命令”当作没有副作用。

## 恢复与替代方案

云端短事务不包住模型或网络；本机先落盘启动意图和事件，再上传。启动中断不自动重启 Claude。只有能核实实例、进程创建时间与进程组归属时才停止遗留进程；不能确认则阻塞并人工处理。恢复上传重复事件和结果不会重复执行。

本版不透明续跑 Claude：保存 session ID 供定位；客户端中断后显式重试产生新 Attempt。原有 DeepAgents checkpoint 恢复不变。

另一方案是完整自托管 Happier + 官方客户端，升级成本低但有第二套账号和同步系统；另一方案完全重写 Claude 协议，减少 Node 依赖但维护成本高。本版选择小型执行层适配，接受维护少量上游派生代码。
