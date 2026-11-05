from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from personal_superagent.workflow.checkpoints import CheckpointError, execution_config, run_workflow
from personal_superagent.workflow.policy import RolePolicy
from personal_superagent.execution.templatetags.markdown import markdown


def payload(directory):
    return {"attempt_id": str(uuid4()), "checkpoint_dir": directory, "mode": "demo", "action": "start",
            "snapshot": {"title": "个人计划", "description": "整理一个每周读书计划", "workflow": execution_config("demo")}}


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_native_agents_checkpoint_interrupt_and_resume(decision):
    with TemporaryDirectory() as directory:
        data = payload(directory)
        events = []
        state = run_workflow(data, lambda kind, value: events.append((kind, value)))
        assert not state["complete"] and not state["documents"]
        assert len(state["pending"]) == 1
        assert {s["role"] for s in state["subtasks"]} == {"writer", "reviewer"}
        assert all(s["state"] == "completed" for s in state["subtasks"])
        calls_before = [value["call_id"] for kind, value in events if kind == "subagent_start"]
        assert len(calls_before) == 2
        assert any(kind == "model" and value.get("parent_call_id") for kind, value in events)
        data["action"] = "resume"
        data["decisions"] = {state["pending"][0]["interrupt_id"]: {"decisions": [{"type": decision}]}}
        resumed_events = []
        final = run_workflow(data, lambda kind, value: resumed_events.append((kind, value)))
        assert final["complete"] and not final["pending"]
        assert not any(kind == "subagent_start" for kind, _ in resumed_events)
        assert bool(final["documents"]) == (decision == "approve")
        if decision == "reject":
            assert "拒绝" in final["result"]


def test_missing_corrupt_and_incompatible_checkpoint():
    with TemporaryDirectory() as directory:
        data = payload(directory)
        data["action"] = "continue"
        with pytest.raises(CheckpointError, match="缺失"):
            run_workflow(data, lambda *args: None)
        data["action"] = "start"
        run_workflow(data, lambda *args: None)
        data["action"] = "continue"
        data["snapshot"]["workflow"]["version"] = "wrong"
        with pytest.raises(CheckpointError, match="变化"):
            run_workflow(data, lambda *args: None)
        data["snapshot"]["workflow"] = execution_config("demo")
        from pathlib import Path
        (Path(directory) / "checkpoint.sqlite3").write_bytes(b"broken-database")
        with pytest.raises(CheckpointError, match="损坏"):
            run_workflow(data, lambda *args: None)


def test_roles_cannot_escalate_or_delegate_recursively():
    from types import SimpleNamespace
    for role in ["supervisor", "writer", "reviewer"]:
        policy = RolePolicy(role)
        for name, args in [("execute", {}), ("read_file", {}), ("task", {"subagent_type": "general-purpose"})]:
            result = policy.wrap_tool_call(SimpleNamespace(tool_call={"id": "blocked", "name": name, "args": args}), lambda _: pytest.fail("越权工具不得执行"))
            assert result.status == "error"
        if role != "supervisor":
            result = policy.wrap_tool_call(SimpleNamespace(tool_call={"id": "blocked", "name": "save_document", "args": {}}), lambda _: pytest.fail("子 Agent 不得保存文档"))
            assert result.status == "error"


def test_markdown_disallows_html_and_script_links():
    html = str(markdown('# 标题\n\n<script>alert(1)</script>\n\n[click](javascript:alert(1))'))
    assert "<h1>标题</h1>" in html
    assert "<script>" not in html
    assert 'href="javascript:' not in html


def test_parallel_approved_documents_are_merged(monkeypatch):
    from personal_superagent.workflow.demo import WorkflowDemoModel
    class TwoDocuments(WorkflowDemoModel):
        def _generate(self, *args, **kwargs):
            result = super()._generate(*args, **kwargs)
            message = result.generations[0].message
            if self.role == "supervisor" and message.tool_calls and message.tool_calls[0]["name"] == "save_document":
                message.tool_calls.append({"name": "save_document", "args": {"name": "补充.md", "content": "# 补充文档"}, "id": str(uuid4()), "type": "tool_call"})
            return result
    monkeypatch.setattr("personal_superagent.workflow.factory.WorkflowDemoModel", TwoDocuments)
    with TemporaryDirectory() as directory:
        data = payload(directory)
        state = run_workflow(data, lambda *args: None)
        assert len(state["pending"]) == 2 and not state["documents"]
        data["action"] = "resume"
        data["decisions"] = {state["pending"][0]["interrupt_id"]: {"decisions": [{"type": "approve"}, {"type": "approve"}]}}
        final = run_workflow(data, lambda *args: None)
        assert final["complete"] and len(final["documents"]) == 2
