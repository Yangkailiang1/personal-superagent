"""业务 Agent：与第一课模型分开，只有无副作用的轻量工具。"""
from typing import Any, Callable
from uuid import uuid4

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from personal_superagent.models import build_model
from personal_superagent.tools import add_numbers


class TextInput(BaseModel):
    text: str = Field(max_length=12000)


@tool(args_schema=TextInput)
def text_statistics(text: str) -> dict[str, int]:
    """计算文本字符数、非空行数与按空白分隔的片段数；不读取任何文件。"""
    return {"characters": len(text), "nonempty_lines": sum(bool(line.strip()) for line in text.splitlines()), "segments": len(text.split())}


TOOLS = [add_numbers, text_statistics]
ALLOWED = {tool.name for tool in TOOLS}


class RestrictedTools(AgentMiddleware):
    """双重限制：模型只看到白名单，实际执行也验证，不能只靠提示词。"""
    def wrap_model_call(self, request, handler):
        return handler(request.override(tools=TOOLS))

    def wrap_tool_call(self, request, handler):
        if request.tool_call["name"] not in ALLOWED:
            return ToolMessage(content="本版不允许该工具。", tool_call_id=request.tool_call["id"], status="error")
        return handler(request)


class TaskDemoModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "task-demo"

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs):
        if isinstance(messages[-1], ToolMessage):
            reply = AIMessage(content="[离线演示] 已通过工具分析本次任务文本：\n" + str(messages[-1].content))
        else:
            text = next(str(m.content) for m in reversed(messages) if isinstance(m, HumanMessage))
            reply = AIMessage(content="", tool_calls=[{
                "name": "text_statistics", "args": {"text": text}, "id": str(uuid4()),
            }])
        return ChatResult(generations=[ChatGeneration(message=reply)])


def run_agent(snapshot: dict, mode: str, emit: Callable[[str, dict], None]) -> str:
    """事件仅为展示，不回灌模型；工具调用说明不会混入最终回答。"""
    graph = create_deep_agent(
        model=TaskDemoModel() if mode == "demo" else build_model(demo=False),
        tools=TOOLS, backend=StateBackend(), middleware=[RestrictedTools()],
        system_prompt=("你是个人任务助手。根据用户目标给出清晰、诚实的结果。"
                       "本版只有加法和文本统计工具；不能访问文件、网络、Shell 或委派。"
                       "无法完成的操作请说明限制，绝不宣称已执行。"),
    )
    answer = ""
    # messages 不持久化为 checkpoint；本版只保证结果与事件落库，不承诺中途续跑。
    for chunk in graph.stream(
        {"messages": [{"role": "user", "content": snapshot["title"] + "\n" + snapshot["description"]}]},
        config={"recursion_limit": 24}, stream_mode="updates",
    ):
        for update in chunk.values():
            if not isinstance(update, dict):
                continue
            for message in update.get("messages", []):
                if isinstance(message, AIMessage):
                    emit("model", {"activity": "模型已返回", "tool_count": len(message.tool_calls)})
                    for call in message.tool_calls:
                        emit("tool_start", {"name": call["name"], "call_id": call["id"]})
                    if not message.tool_calls:
                        answer = message.text
                elif isinstance(message, ToolMessage):
                    emit("tool_end", {"name": message.name, "call_id": message.tool_call_id, "status": message.status})
    if not answer:
        raise RuntimeError("执行没有返回最终回答")
    return answer
