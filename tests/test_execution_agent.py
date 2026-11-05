from types import SimpleNamespace

from personal_superagent.execution.agent import ALLOWED, RestrictedTools, run_agent


def test_business_demo_runs_real_tool_without_lesson_prompt():
    events = []
    answer = run_agent({"title": "整理旅行计划", "description": "京都三日游"}, "demo", lambda kind, data: events.append((kind, data)))
    assert "离线演示" in answer
    assert any(kind == "tool_start" and data["name"] == "text_statistics" for kind, data in events)
    assert any(kind == "tool_end" for kind, _ in events)


def test_builtin_tool_is_blocked_at_execution_boundary():
    def forbidden_handler(request):
        raise AssertionError("不能执行原生文件或委派工具")
    middleware = RestrictedTools()
    for name in ["write_file", "read_file", "execute", "task"]:
        message = middleware.wrap_tool_call(SimpleNamespace(tool_call={"name": name, "id": "blocked"}), forbidden_handler)
        assert message.status == "error"


def test_only_allowlisted_schemas_are_exposed():
    class Request:
        def override(self, *, tools):
            return tools
    tools = RestrictedTools().wrap_model_call(Request(), lambda tools: tools)
    assert {tool.name for tool in tools} == ALLOWED == {"add_numbers", "text_statistics"}
