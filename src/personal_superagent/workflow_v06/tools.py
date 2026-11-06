"""交付文档先进入图状态，Worker 再幂等投影到业务数据库，不直接写文件。"""

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, Field


class DocumentInput(BaseModel):
    name: str = Field(pattern=r"^[\w\-][\w.\-]{0,75}\.md$")
    content: str = Field(min_length=1, max_length=12000)


@tool(args_schema=DocumentInput)
def save_document(name: str, content: str, runtime: ToolRuntime) -> Command:
    """申请保存 Markdown 交付文档。必须先经用户批准，拒绝后不能声称已保存。"""
    documents = dict(runtime.state.get("documents", {}))
    if len(documents) >= 2 and runtime.tool_call_id not in documents:
        raise ValueError("每次执行最多保存两份文档")
    documents[runtime.tool_call_id] = {"name": name, "content": content}
    return Command(
        update={
            "documents": documents,
            "messages": [
                ToolMessage(
                    content=f"已批准保存：{name}", tool_call_id=runtime.tool_call_id
                ),
            ],
        }
    )
