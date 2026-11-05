import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from personal_superagent.agent import build_agent
from personal_superagent.models import build_model
from personal_superagent.tools import add_numbers


def test_real_graph_executes_tool():
    state = build_agent(demo=True).invoke(
        {"messages": [{"role": "user", "content": "计算 8 + 13"}]},
        config={"recursion_limit": 12},
    )
    messages = state["messages"]
    request = next(m for m in messages if isinstance(m, AIMessage) and m.tool_calls)
    result = next(m for m in messages if isinstance(m, ToolMessage))
    assert result.tool_call_id == request.tool_calls[0]["id"]
    assert request.tool_calls[0]["args"] == {"a": 8, "b": 13}
    assert result.content == "21"
    assert "21" in messages[-1].content
    assert not messages[-1].tool_calls


@pytest.mark.parametrize("args", [{"a": "17", "b": 25}, {"a": 1_000_001, "b": 25}])
def test_invalid_tool_arguments_rejected(args):
    with pytest.raises(ValidationError):
        add_numbers.invoke(args)


def test_real_mode_never_silently_falls_back(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    with pytest.raises(ValueError, match="MODEL_API_KEY"):
        build_model(demo=False)
