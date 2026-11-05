"""固定模型响应仍走真实工具、子 Agent、原生审批和 checkpoint，不调用供应商。"""
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from personal_superagent.models import LessonModel


class WorkflowDemoModel(LessonModel):
    role: str = "supervisor"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        turn = messages[max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage)):]
        calls = [c for m in turn if isinstance(m, AIMessage) for c in m.tool_calls]
        names = [c["name"] for c in calls]
        text = str(turn[0].content)[:4000]

        def call(name, args):
            return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": str(uuid4())}])

        todos = [
            {"content": "整理用户材料", "status": "in_progress"},
            {"content": "检查草稿与交付", "status": "pending"},
        ]
        if self.role != "supervisor":
            if "text_statistics" not in names:
                reply = call("text_statistics", {"text": text})
            elif self.role == "writer":
                reply = AIMessage(content=f"# 任务整理草稿\n\n## 用户材料\n\n{text}\n\n## 建议步骤\n\n1. 明确目标与范围。\n2. 按验收标准逐项完成。\n\n> 离线演示：没有检索外部信息。")
            else:
                reply = AIMessage(content="检查意见：材料来自用户输入；未核实外部事实。建议用户核对范围和验收标准。")
        elif "write_todos" not in names:
            reply = call("write_todos", {"todos": todos})
        elif names.count("task") == 0:
            reply = call("task", {"subagent_type": "writer", "description": "请整理以下用户材料，返回 Markdown 草稿：\n" + text})
        elif names.count("task") == 1:
            draft = next(str(m.content) for m in reversed(turn) if isinstance(m, ToolMessage) and m.name == "task")
            reply = call("task", {"subagent_type": "reviewer", "description": "检查这份草稿，指出未验证信息：\n" + draft})
        elif "save_document" not in names:
            draft = next(str(m.content) for m in turn if isinstance(m, ToolMessage) and m.name == "task")
            reply = call("save_document", {"name": "任务整理.md", "content": draft[:11000]})
        elif names.count("write_todos") < 2:
            reply = call("write_todos", {"todos": [{**t, "status": "completed"} for t in todos]})
        else:
            rejected = any(isinstance(m, ToolMessage) and m.name == "save_document" and m.status == "error" for m in turn)
            reply = AIMessage(content=("## 任务结束\n\n你已拒绝保存，本轮未发布交付文档。" if rejected else "## 任务完成\n\n已由内容整理与质量检查两个子 Agent 协作，并按你的批准保存文档。") + "\n\n> 本次为离线演示，没有进行外部检索。")
        return ChatResult(generations=[ChatGeneration(message=reply)])
