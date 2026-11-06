# V0.5 运行与配置

## 使用服务器工作台

```bash
cd /Users/yangkailiang/Documents/DeepAgents/personal-superagent
uv run --locked --group deploy python scripts/deploy/remote.py tunnel
```

访问 http://127.0.0.1:18002/ ，原账号登录，默认进入任务看板。选择“需求对话”，以演示模式输入需求，等待草稿；可以编辑后保存、清空已解决的问题、明确接受假设，再确认生成任务。随后单独启动任务，在看板跟踪阶段并处理审批。演示不会理解任意目标，其固定响应明确标注。

任务详情“来源与历史”可返回需求会话、查看所有 Attempt，并按游标加载历史事件。看板取消历史不占主要列；运行失败不自动重试。设备授权与运行方法沿用 V0.4。

## 配置本项目真实模型

准备一个支持工具调用的 OpenAI 兼容服务以及本项目独立 Key。不要把 Key 发到聊天、Git 或命令行参数。终端运行：

```bash
uv run --locked --group deploy python scripts/deploy/configure_model.py
```

脚本交互读取模型名、HTTPS Base URL、隐藏 Key，通过固定指纹 SSH stdin 写服务器 runtime.env（0600），并重启本项目 Web/Worker；请先等待活动任务结束。未决审批的模型配置若发生改变，按原兼容检查拒绝恢复，不能承诺随意换模型后续跑。不要借配置操作强行重试未知本地写入。

填写完成时状态是“待验证”。以下命令**会产生真实 API 费用，正常共两次模型请求**，需用户主动运行：

```bash
uv run --locked --group deploy python scripts/deploy/check_model.py
```

验证使用无副作用工具，成功显示“可用”。失败给通用提示，不记录供应商原始异常。模型状态保存在服务器运行目录，绑定配置指纹；更换配置需要重新验证。开关或验证未通过时不能启动真实接待/后台任务。

验证通过后在需求对话选“真实模型”，生成并确认草稿；启动正式任务时也要选择“真实模型”。两处模式独立，演示记录不会被更名成真实结果。

## 本机开发

```bash
uv sync --locked --group browser --group deploy
docker compose --env-file .env.dev up -d --wait
uv run --env-file .env.dev --locked manage.py migrate
npm ci --prefix frontend
npm run build --prefix frontend
uv run --env-file .env.dev --locked manage.py runserver 127.0.0.1:8002 --noreload
# 另一终端
uv run --env-file .env.dev --locked manage.py agent_worker
```

Node 24；Python 3.12。本机真实模式请在本项目专用私密环境文件配置 MODEL_NAME、MODEL_BASE_URL、MODEL_API_KEY 和 ALLOW_REAL_MODE=1，Web/Worker 使用同一环境。执行 `uv run --env-file 该私密文件 --locked manage.py model_check` 显式验证，绝不提交配置。

测试：`uv run --env-file .env.dev --locked manage.py test personal_superagent.tasks personal_superagent.execution personal_superagent.devices personal_superagent.web.tests personal_superagent.intake --noinput` 和 `uv run --locked pytest -q`。浏览器 scripts/browser_v05.py 必须用专用临时账号；它会创建需求、任务及演示交付，不使用用户真实资料。

发布沿用按提交代码包、静态预压缩、迁移前备份及 systemd。新迁移 tasks.0005、intake.0001/0002 保留旧数据。本版不开放公网网页，不向其他用户提供服务器 SSH 凭据。
