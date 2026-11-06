"""小型受限 Agent 共用 Worker：路由、知识整理和定时巡检。"""

import json
import uuid
from pydantic import BaseModel, Field, ConfigDict
from langchain_core.tools import tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain.agents.middleware import AgentMiddleware
from deepagents import create_deep_agent
from personal_superagent.models import build_model


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    base: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=12000)
    sources: list[str] = Field(min_length=1, max_length=20)


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = ""
    reason: str = Field(default="", max_length=1000)
    report: str = Field(default="", max_length=6000)
    changes: list[Change] = Field(default_factory=list, max_length=8)


class Scripted(BaseChatModel):
    payload: dict

    @property
    def _llm_type(self):
        return "explicit-scripted-job"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, **kwargs):
        m = (
            AIMessage(content="建议已形成（离线演示）")
            if isinstance(messages[-1], ToolMessage)
            else AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "submit_result",
                        "id": "result",
                        "args": {"result": self.payload},
                    }
                ],
            )
        )
        return ChatResult(generations=[ChatGeneration(message=m)])


class Bound(AgentMiddleware):
    def __init__(self, emit, limit=8):
        self.limit = min(8, limit)
        self.calls = 0
        self.emit = emit

    def wrap_model_call(self, request, handler):
        self.calls += 1
        if self.calls > self.limit:
            raise ValueError("最多八次模型请求")
        self.emit("model", {"role": "management", "call": self.calls})
        return handler(
            request.override(
                tools=[
                    t
                    for t in request.tools
                    if (t.get("name") if isinstance(t, dict) else t.name)
                    == "submit_result"
                ]
            )
        )

    def wrap_tool_call(self, request, handler):
        if request.tool_call["name"] != "submit_result":
            raise ValueError("管理角色无此权限")
        return handler(request)


def run_job(snapshot, mode, emit):
    kind = snapshot["kind"]
    payload = {"report": "离线演示：检查了明确提供的材料，不自动改动任务或知识。"}
    if kind == "inspection":
        payload = {
            "report": f"离线演示：当前有 {len(snapshot.get('tasks', []))} 项未完成任务、{len(snapshot.get('unorganized', []))} 份未整理材料。请核对阻塞任务及需要入库的资料；未自动修改任务或知识。"
        }
    if kind == "routing":
        payload = {
            "agent_id": snapshot["candidates"][0]["id"],
            "reason": "在服务端已检查的候选中，优先历史职责和资源匹配（离线演示）",
        }
    if kind == "knowledge" and snapshot["sources"]:
        source = snapshot["sources"][0]
        page = next(iter(snapshot["pages"]), None)
        payload = {
            "report": "整理材料为带来源页面（离线演示）",
            "changes": [
                {
                    "slug": page["slug"] if page else "notes",
                    "base": page["revision"] if page else 0,
                    "content": source["content"][:10000],
                    "sources": [source["id"]],
                }
            ],
        }
    saved = {}

    @tool
    def submit_result(result: Output) -> str:
        """提交建议，不能直接发布任务或修改正式知识页。"""
        nonlocal saved
        saved = result.model_dump()
        return "建议已暂存"

    bound = Bound(emit, snapshot.get("max_calls", 8))
    graph = create_deep_agent(
        model=Scripted(payload=payload) if mode == "demo" else build_model(demo=False),
        tools=[submit_result],
        middleware=[bound],
        system_prompt="你是受限的"
        + kind
        + "助手。仅处理输入快照。路由从候选中选择负责人并解释。知识整理按来源更新规范页面，保留矛盾和不确定；检查重复、链接、索引，给出变更建议。巡检只建议跟进，不发布任务或修改知识。所有非平凡事实必须引用给定来源 ID。不得执行其他工具。调用 submit_result 完成。",
    )
    graph.invoke(
        {
            "messages": [
                {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)}
            ]
        },
        config={"recursion_limit": 16},
    )
    result = Output.model_validate(saved).model_dump()
    result["calls"] = bound.calls
    encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded) > 30000:
        raise ValueError("建议结果过长，请分批整理")
    return encoded


def enqueue_job(user, kind, snapshot, mode="demo"):
    from django.conf import settings
    from personal_superagent.model_status import status

    if mode not in {"demo", "real"}:
        raise ValueError("模式无效")
    if mode == "real" and (
        not settings.ALLOW_REAL_MODE or status()["state"] != "ready"
    ):
        raise ValueError("真实模型未就绪")
    from personal_superagent.tasks.models import Task
    from personal_superagent.execution.models import Attempt
    from personal_superagent.execution.lifecycle import append_event

    task = Task.objects.create(
        owner=user, kind=kind, title=kind, description=kind, status="queued"
    )
    attempt = Attempt.objects.create(
        task=task,
        request_key=uuid.uuid4(),
        mode=mode,
        input_snapshot={"kind": kind, **snapshot},
    )
    append_event(attempt, "queued", {"role": kind})
    return attempt
