# V0.6 运行方法

## 网页

保持 SSH 隧道并访问 http://127.0.0.1:18002/ ，默认进入主对话。描述目标后回答三个候选项或自定义输入，核对 Plan、依赖与工具，选择模式和限额，点击“发布并执行”。系统自动路由、按依赖派工；审批与失败在看板处理。高级编辑保留结构化 JSON，不再要求用户日常填写整页表单。

服务器模型配置沿用 V0.5 的 configure_model.py / check_model.py。没有独立 Key 时只用演示，固定响应不代表真实理解效果。

## 本机独立 Agent

真实主对话和路由仍需先配置云端模型；本机模型使用自己的 Key，独立配置和验证，不替代云端 Key。每台设备使用不同配置目录和一次性绑定码，不能复制 token：

```bash
uv run --locked superagent-client --config-dir ~/.personal-superagent pair --url http://127.0.0.1:18002 --code 网页绑定码 --name 我的电脑
uv run --locked superagent-client --config-dir ~/.personal-superagent grant --name 笔记 --path /你的专用资料目录 --tools list_files,read_text,write_text --ack-cloud-transfer
uv run --locked superagent-client --config-dir ~/.personal-superagent agent-config
# 下条命令显式调用模型两次，可能收费
uv run --locked superagent-client --config-dir ~/.personal-superagent agent-check
uv run --locked superagent-client --config-dir ~/.personal-superagent agent-run
```

agent-config 支持 HTTPS 兼容服务或 localhost HTTP 模型，Key 隐藏输入只存本机 0600 model.json。模型须支持工具调用。未配置真实模型时 agent-run 仍声明演示能力，不冒充真实模型。

两台电脑分别建立可访问云端的 HTTPS 或 SSH 隧道；不要给其他用户分发服务器 SSH 凭证。设备只主动连接，不开放本机入站端口。本版支持 macOS/Linux/WSL2，原生 Windows 不支持安全文件工具。

旧 `superagent-client run` 继续处理旧云端任务的远程文件请求；`agent-run` 是独立模型执行器。当前工作图中的本地写入仍须单次网页批准，文件只新建、不覆盖。

## 工具配置

云端：`uv run --locked --group deploy python scripts/deploy/configure_tools.py`，隐藏输入本项目独立搜索/生图 Key，或指定 MCP JSON 文件。它会重启本项目服务，请先等待活动任务结束。未发送搜索或生图验证请求。

本机：`uv run --locked superagent-client agent-tools`。凭证保留本机；工具配置变化后重新 agent-check。MCP 配置示例：

```json
[{"name":"docs","transport":"streamable_http","url":"https://你的服务/mcp","allowed_tools":["search_docs"]}]
```

本机也可用 `transport=stdio`，配置固定 command/args，仅由用户终端设置，不由云端任务下发。白名单不得包含 Shell 或原生文件修改工具，MCP 调用仍需审批。缺少配置时工具不可用，不会用模拟搜索/图片替代真实结果。

## 设备掉线与人工处理

断线不代表没有副作用。保存本机 runs、agent-ledger.sqlite3 和 outbox，不要删账本强行重跑。客户端重启先确认旧进程 PID+创建时间、补报已知结果；started 后崩溃只报告中断，不重放图。

服务器显示未知停止状态时，先在原设备检查进程及文件，再用任务详情“我已在原设备确认进程停止”记录人工确认。它不是系统独立验证。显式恢复在原设备读取原 checkpoint，缺失或不兼容失败，不从头覆盖；重试另建 Attempt。

## 知识与巡检

知识页添加明确选择的原始文本或当前用户文档产物 ID，选材料整理，查看建议后确认修订。原材料不覆盖，规范页保留来源与历史；冲突要求重新整理。

巡检默认关闭；开启后每日 09:00（默认 Asia/Shanghai）一次、最多八次模型请求，仅提供站内建议。可随时关闭。模型配置失效记录当天未执行，不无限补跑。

## 开发和发布

Python 3.12、uv、Node 24。使用本项目 `.env.dev` 和 PostgreSQL；migrate 后分别启动 Django 与 agent_worker。前端 `npm ci --prefix frontend && npm run build --prefix frontend`。新增编号迁移保留数据，旧图源码不能格式化或修改。

测试包含原有 Django/Agent 回归、collaboration 编排和两个独立运行目录的设备测试，以及 scripts/browser_v06.py。两实例同机验收不等于不同物理设备验收。真实模型/搜索/生图/MCP 服务验收单独记录，不自动花费额度。
