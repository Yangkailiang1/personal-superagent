# 第一课：最小 DeepAgents 单 Agent

后续记录：你已将离线参数改成 8 和 13，目前实际输出为 21；以下保留初始参考示例 17 + 25 的讲解。已按你的修改同步回归测试和 CLI 提示，乘法工具保留，未替你继续扩展练习。

## 1. 本课要理解什么

先跑通一个真正的执行图：用户消息 → 模型提出工具调用 → Python 执行工具 → 工具消息交回模型 → 最终回答。

工具调用不是模型自己执行 Python。模型返回工具名、参数和调用 ID；框架找到已注册工具并运行，把结果放进 `ToolMessage`，用同一个调用 ID 关联请求与结果。模型看到结果后再次回复。框架负责循环，工具负责确定性计算。

本课故意只计算 17 + 25。没有 Django 页面、数据库、设备或队列；后续课程逐步接入。离线模型是固定脚本，不具备自然语言理解能力，但工具执行和 DeepAgents 图是真实的。

## 2. 文件与调用关系

```text
cli.main()
  → agent.build_agent(demo=...)
      → models.build_model(demo=...)
      → 注册 tools.add_numbers
      → create_deep_agent(...)
  → graph.invoke(messages, recursion_limit=12)
  → 读取最终 messages，打印工具请求、结果和回答
```

| 文件 | 为什么存在 |
| --- | --- |
| `pyproject.toml` / `uv.lock` | 声明直接依赖 / 锁定完整解析结果；不要手动改 lock |
| `src/personal_superagent/tools.py` | 工具参数与实际业务计算，和模型调用分开 |
| `src/personal_superagent/models.py` | 离线模型与真实供应商入口，不把密钥放进工具 |
| `src/personal_superagent/agent.py` | 组装执行图，不处理网页请求或任务调度 |
| `src/personal_superagent/cli.py` | 参数、调用和输出；后续可增加网页入口而复用工厂 |
| `tests/test_lesson.py` | 验证真实工具链路、参数校验及禁止静默降级 |

## 3. 环境与运行

在终端逐条执行：

```bash
cd /Users/yangkailiang/Documents/DeepAgents/personal-superagent
uv --version
uv sync --locked
uv run --locked python --version
uv run --locked superagent --demo
uv run --locked pytest -q
```

Python 应为 3.12。若本机没有此版本，可先运行 `uv python install 3.12`，再同步。首次下载需要联网，不需要复用旧项目虚拟环境。

预期关键输出：

```text
离线模式：固定计算 17 + 25，不解释自定义 prompt。
[模型请求工具] add_numbers {'a': 17, 'b': 25}
[工具返回] 42
[最终回答] 计算结果：42（离线固定示例）
```

这里打印的是执行完成后的消息链，**还不是实时流式输出**。流式、保存和恢复是后续课，不要把终端记录误认为已实现的历史系统。

## 4. 关键函数逐个看

### `add_numbers(a, b) -> str`

输入两个整数，返回计算结果字符串。`AddInput` 用 Pydantic 描述 schema；`strict=True` 拒绝把字符串偷偷转换成整数，范围限制阻止异常大输入。`@tool` 把函数描述和 schema 暴露给模型。不要用提示词代替服务端参数验证。

通过 `add_numbers.invoke({"a": 17, "b": 25})` 会先验证 schema 再调用函数。工具调用 ID 不属于业务参数，框架在消息层管理。

### `build_model(*, demo: bool) -> BaseChatModel`

输入显式模式；输出统一模型接口。离线返回 `LessonModel`，真实模式读取本项目约定的环境变量并构造 `ChatOpenAI`。缺配置直接报错，不自动改用离线模型，否则容易把演示误判为真实成功。

`LessonModel._generate()` 第一次返回带 `tool_calls` 的 AIMessage，第二次读取 ToolMessage 并返回回答。它只用于这一轮固定样例。不要将这种“看最后一条消息”的实现复制到生产编排器。

`bind_tools()` 是框架绑定工具的接口：离线模型忽略它，真实供应商适配器负责把 schema 发给模型。忽略绑定只有在这个固定脚本里合理。

### `build_agent(*, demo: bool) -> CompiledStateGraph`

输入模式；输出已编译图。这里只注册我们写的一个业务工具；DeepAgents 还会带原生文件等能力，因此工具总数不等于一个。

明确使用 `StateBackend`，文件是图状态中的虚拟内容，不映射到电脑目录，也不具备执行宿主 Shell 的实现。本课通过提示词要求不使用额外能力；**提示词不是安全权限控制**。后续需要独立实现工具授权，不能把这课工厂直接当成生产安全边界。

### `main() -> None`

选择模式、提交一条用户消息、调用图并输出消息。`recursion_limit=12` 限制图步骤以防固定例子意外不收敛，它不是任务超时或费用硬上限。真实模型配置了单次请求超时和零自动重试；完整取消、总预算及恢复仍需后续实现。

## 5. 可选：真实模型验证

不是本课必做，不运行也不影响离线验收。供应商必须支持工具调用。不要复用其他项目 `.env`；这里不自动加载 `.env`。

在当前终端设置 `MODEL_API_KEY`、`MODEL_NAME`，如有需要设置 `MODEL_BASE_URL`。在自己的终端安全输入密钥，不发给聊天、不写入 Git；Base URL 通常为供应商提供的 `/v1` 地址。

```bash
uv run --locked superagent --real --prompt '请调用工具计算 17 + 25。'
```

这会调用供应商并可能收费。真实模式输出是否选择工具取决于模型；应核对是否出现工具请求和工具返回，不能只看答案是 42。

## 6. 你亲手完成的练习

1. 按 `tools.py → models.py → agent.py → cli.py` 阅读，自己写出上述调用关系。
2. 在离线模型中将固定参数改成 8 和 13，运行确认工具与最终结果都是 21，再恢复或同步更新测试。
3. 在本地交互式 Python 中调用 `add_numbers.invoke({"a": "17", "b": 25})`，解释为什么报 ValidationError，而不是得到 42。
4. 自己添加一个 `multiply_numbers` 工具并注册；让离线模型调用它，更新一条测试验证结果来自工具，而不是模型写死。
5. 解释：为何多 Agent、Django 和数据库暂时不需要？为何把提示词写成“不访问其他目录”还不算权限系统？

请先完成这些练习，再开始第二课。当前仓库的参考实现通过，不代表你已经完成练习。后续检查代码和运行结果后，更新进度表。

## 7. 常见问题

- `uv: command not found`：先安装 uv 并重新打开终端，不改成系统 Python 直接安装所有包。
- 找不到模块：确认在项目根目录执行 `uv sync --locked`，再用 `uv run`。
- 真实模式报错：检查两个必填变量、供应商 URL、网络和模型工具调用支持。CLI 不打印可能含秘密的原始供应商异常。
- 改 prompt 后离线结果没变：这是固定脚本的设计，不是模型真的忽略任务。自由任务用真实模式或等待后续可测试的模型适配。
- 退出后没有历史：本课未接 checkpointer，这是明确范围。不要自行把整套消息 JSON 当作任务数据库。
