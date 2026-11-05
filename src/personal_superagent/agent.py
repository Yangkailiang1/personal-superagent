"""Agent 工厂只组装能力，不承担网页或任务队列职责。"""

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langgraph.graph.state import CompiledStateGraph

from personal_superagent.models import build_model
from personal_superagent.tools import add_numbers


def build_agent(*, demo: bool) -> CompiledStateGraph:
    """创建独立图；文件仅存于内存状态，不连接宿主目录或 Shell。"""
    return create_deep_agent(
        model=build_model(demo=demo),
        tools=[add_numbers],
        backend=StateBackend(),
        system_prompt=(
            "你是教学助手。加法必须调用 add_numbers，然后简洁报告结果。"
            "本课仅演示计算，不使用文件工具或委派其他 Agent。"
        ),
    )
