"""验证真实 DeepAgents 图的交互契约，不发付费模型请求。"""
import json
from unittest.mock import patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from personal_superagent.collaboration.conversation_agent import run


class ScriptedModel(BaseChatModel):
    replies: list
    calls: int = 0
    forced: bool = False
    forced_tools: list = []

    @property
    def _llm_type(self):
        return "conversation-contract-test"

    def bind_tools(self, tools, **kwargs):
        if kwargs.get("tool_choice") == "required":
            self.forced = True
            names = {t.name if hasattr(t, "name") else t["name"] for t in tools}
            assert names <= {"ask_user", "update_plan"}
            self.forced_tools.append(names)
        return self

    def _generate(self, messages, **kwargs):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=reply)])


def tool(name, args):
    return AIMessage(content="", tool_calls=[{"id": name, "name": name, "args": args}])


def invoke(model):
    with patch("personal_superagent.collaboration.conversation_agent.build_model", return_value=model):
        return json.loads(run({"text": "请帮我建模一个苹果", "draft": {}, "messages": []}, "real", lambda *args: None))


def test_transition_text_is_completed_with_actual_choice():
    model = ScriptedModel(replies=[
        tool("query_knowledge", {"query": "苹果"}),
        AIMessage(content="我先确认一个关键点。"),
        tool("ask_user", {"question": {"prompt": "选择建模风格", "options": ["写实", "卡通", "低多边形"]}}),
        AIMessage(content="请选择。"),
    ])
    result = invoke(model)
    assert model.forced
    assert result["question"]["options"] == ["写实", "卡通", "低多边形"]
    assert result["draft"] == {}
    assert model.calls == 4


def test_noncompliant_model_fails_instead_of_silent_success():
    model = ScriptedModel(replies=[AIMessage(content="我会继续处理。")])
    with pytest.raises(ValueError, match="没有生成可操作"):
        invoke(model)
    assert model.calls == 2


def test_progress_query_can_end_without_spurious_question():
    model = ScriptedModel(replies=[tool("read_tasks", {}), AIMessage(content="当前暂无任务。")])
    assert invoke(model)["question"] is None
    assert model.calls == 2


def test_existing_question_does_not_trigger_extra_model_call():
    model = ScriptedModel(replies=[
        tool("ask_user", {"question": {"prompt": "选择风格", "options": ["写实", "卡通", "低多边形"]}}),
        AIMessage(content="请选择。"),
    ])
    assert invoke(model)["question"] is not None
    assert not model.forced
    assert model.calls == 2


def test_plan_questions_must_produce_three_choices_without_dropping_question():
    plan = {"title": "苹果模型", "goal": "建模苹果", "materials": "用户需求", "deliverables": ["模型"], "acceptance": ["可打开"], "device_needs": "本机", "questions": ["需要何种表皮细节？"], "assumptions": [], "steps": []}
    model = ScriptedModel(replies=[
        tool("update_plan", {"plan": plan}), AIMessage(content="请先确认细节。"),
        tool("ask_user", {"question": {"prompt": "需要何种表皮细节？", "options": ["光滑表面", "细小斑点", "斑点与轻微瑕疵"]}}),
        AIMessage(content="请选择。"),
    ])
    result = invoke(model)
    assert result["draft"]["questions"] == plan["questions"]
    assert len(result["question"]["options"]) == 3
    assert model.forced_tools == [{"ask_user"}]


def test_plan_with_unresolved_questions_cannot_silently_finish():
    plan = {"title": "苹果模型", "goal": "建模苹果", "materials": "用户需求", "deliverables": ["模型"], "acceptance": ["可打开"], "device_needs": "本机", "questions": ["需要何种表皮细节？"], "assumptions": [], "steps": []}
    model = ScriptedModel(replies=[tool("update_plan", {"plan": plan}), AIMessage(content="请自行回答。")])
    with pytest.raises(ValueError, match="没有生成澄清选项"):
        invoke(model)
