"""角色白名单作用于模型 schema 和执行边界，不能只通过提示词控制权限。"""
import threading
from contextvars import ContextVar

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.config import get_config

MODEL_SLOT = threading.Semaphore(1)
ROLES = {"writer", "reviewer"}
PARENT_CALL = ContextVar("parent_call", default="")


class RolePolicy(AgentMiddleware):
    def __init__(self, role: str, emit=lambda kind, data: None):
        self.role = role
        self.emit = emit
        self.allowed = {"add_numbers", "text_statistics"}
        if role == "supervisor":
            self.allowed |= {"task", "write_todos", "save_document"}

    def wrap_model_call(self, request, handler):
        tools = [t for t in request.tools if (t.get("name") if isinstance(t, dict) else t.name) in self.allowed]
        with MODEL_SLOT:
            self.emit("model", {"role": self.role, "parent_call_id": PARENT_CALL.get(), "namespace": get_config().get("configurable", {}).get("checkpoint_ns", "")[:300]})
            return handler(request.override(tools=tools))

    def wrap_tool_call(self, request, handler):
        call = request.tool_call
        allowed = call["name"] in self.allowed
        if call["name"] == "task":
            allowed = allowed and call["args"].get("subagent_type") in ROLES
        if not allowed:
            return ToolMessage(content="该角色无权调用此工具或委派目标。", tool_call_id=call["id"], status="error")
        parent = PARENT_CALL.get()
        self.emit("tool_start", {"name": call["name"], "call_id": call["id"], "role": self.role, "parent_call_id": parent})
        marker = None
        if call["name"] == "task":
            marker = PARENT_CALL.set(call["id"])
            self.emit("subagent_start", {"call_id": call["id"], "role": call["args"]["subagent_type"], "description": call["args"].get("description", "")[:8000]})
        try:
            result = handler(request)
            if call["name"] == "write_todos":
                self.emit("plan", {"todos": call["args"]["todos"]})
            self.emit("tool_end", {"name": call["name"], "call_id": call["id"], "role": self.role, "parent_call_id": parent})
            if marker is not None:
                self.emit("subagent_end", {"call_id": call["id"], "state": "completed"})
            return result
        except Exception:
            if marker is not None:
                self.emit("subagent_end", {"call_id": call["id"], "state": "failed"})
            raise
        finally:
            if marker is not None:
                PARENT_CALL.reset(marker)
