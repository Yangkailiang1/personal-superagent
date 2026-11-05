from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.graph import DeepAgentState
from langchain.agents.middleware import TodoListMiddleware
from typing import Annotated

from personal_superagent.execution.agent import TOOLS
from personal_superagent.models import build_model
from .demo import WorkflowDemoModel
from .policy import RolePolicy
from .tools import save_document


def merge_documents(previous: dict, updates: dict) -> dict:
    """并行批准多份文档时按工具调用 ID 合并，不能最后写入覆盖另一份。"""
    result = dict(previous)
    for key, document in updates.items():
        if key in result and result[key] != document:
            raise ValueError("同一文档调用不能修改已保存内容")
        result[key] = document
    if len(result) > 2:
        raise ValueError("每次执行最多保存两份文档")
    return result


class WorkflowState(DeepAgentState):
    documents: Annotated[dict, merge_documents]


def build_workflow(*, mode: str, checkpointer, emit=lambda kind, data: None):
    """不同角色共享模型并发槽，白名单独立；checkpoint 由调用方管理生命周期。"""
    def model(role):
        return WorkflowDemoModel(role=role) if mode == "demo" else build_model(demo=False)

    return create_deep_agent(
        model=model("supervisor"), backend=StateBackend(), checkpointer=checkpointer,
        tools=[*TOOLS, save_document], state_schema=WorkflowState,
        middleware=[TodoListMiddleware(), RolePolicy("supervisor", emit)],
        interrupt_on={"save_document": {"allowed_decisions": ["approve", "reject"]}},
        system_prompt=("你是个人任务主助手。先用 write_todos 制订计划，按需委派 writer 整理、reviewer 检查。"
                       "只处理用户提供的材料，不具备网络、文件或 Shell 权限。子 Agent 只返回草稿。"
                       "最终文档用 save_document 申请用户批准；拒绝后不要重复申请或宣称已保存。"
                       "把未验证事实写清楚，最终回答独立于执行过程。"),
        subagents=[{
            "name": role, "description": description, "model": model(role), "tools": TOOLS,
            "system_prompt": description + "。只处理收到的文本，返回简洁结果，不委派、不保存文档，不声称核实外部信息。",
            "middleware": [RolePolicy(role, emit)], "interrupt_on": {},
        } for role, description in [("writer", "内容整理，撰写 Markdown 草稿"), ("reviewer", "质量检查，指出遗漏、矛盾与未验证内容")]],
    )
