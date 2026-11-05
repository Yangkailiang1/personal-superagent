"""模型适配：离线脚本用于教学，不假装能理解任意任务。"""

import os
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI


class LessonModel(BaseChatModel):
    """固定请求 8 + 13，第二次调用读取真实工具结果。"""

    @property
    def _llm_type(self) -> str:
        return "lesson-offline"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "LessonModel":
        # 仅离线模型忽略工具绑定；真实模型由供应商适配器发送工具 schema。
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        last = messages[-1]
        if isinstance(last, ToolMessage):
            reply = AIMessage(content=f"计算结果：{last.content}（离线固定示例）")
        else:
            reply = AIMessage(content="", tool_calls=[{
                "name": "add_numbers", "args": {"a": 8, "b": 13}, "id": "lesson-add-1",
            }])
        return ChatResult(generations=[ChatGeneration(message=reply)])


def build_model(*, demo: bool) -> BaseChatModel:
    """输入显式模式，输出支持工具调用的模型；配置缺失立即报错。"""
    if demo:
        return LessonModel()
    key = os.environ.get("MODEL_API_KEY", "").strip()
    name = os.environ.get("MODEL_NAME", "").strip()
    if not key or not name:
        raise ValueError("真实模式需要 MODEL_API_KEY 和 MODEL_NAME；离线请使用 --demo。")
    return ChatOpenAI(
        api_key=key, model=name,
        base_url=os.environ.get("MODEL_BASE_URL") or None,
        timeout=30, max_retries=0,
    )
