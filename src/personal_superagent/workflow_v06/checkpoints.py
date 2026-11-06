"""每个 Attempt 的 checkpoint 隔离在固定 UUID 目录，恢复前检查版本和完整性。"""

import hashlib
from importlib.metadata import version
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from . import VERSION
from .factory import build_workflow
from .context import CURRENT


class CheckpointError(ValueError):
    pass


def runtime_root() -> Path:
    return Path(
        os.environ.get(
            "AGENT_RUNTIME_DIR", Path(__file__).resolve().parents[3] / ".runtime"
        )
    ).resolve()


def checkpoint_dir(attempt_id) -> Path:
    return runtime_root() / str(UUID(str(attempt_id)))


def execution_config(mode: str) -> dict:
    endpoint = os.environ.get("MODEL_BASE_URL", "")
    name = os.environ.get("MODEL_NAME", "") if mode == "real" else "workflow-demo"
    code_hash = hashlib.sha256()
    for file in sorted(Path(__file__).parent.glob("*.py")):
        code_hash.update(file.read_bytes())
    code_hash.update(
        (
            version("deepagents")
            + version("langgraph")
            + version("langgraph-checkpoint-sqlite")
        ).encode()
    )
    return {
        "version": VERSION,
        "code_hash": code_hash.hexdigest(),
        "model": name,
        "endpoint_hash": hashlib.sha256(endpoint.encode()).hexdigest()
        if mode == "real"
        else "demo",
    }


@contextmanager
def open_graph(
    directory: str | Path,
    *,
    mode: str,
    action: str,
    frozen: dict,
    emit=lambda kind, data: None,
    local_scope=None,
):
    directory = Path(directory)
    db = directory / "checkpoint.sqlite3"
    if frozen != execution_config(mode):
        raise CheckpointError("执行代码或模型配置发生变化，不能恢复旧执行。")
    if action != "start":
        if not db.is_file():
            raise CheckpointError("checkpoint 缺失，不能恢复；请新建执行重试。")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink() or db.is_symlink():
        raise CheckpointError("checkpoint 路径不允许符号链接")
    connection = sqlite3.connect(db, check_same_thread=False)
    try:
        os.chmod(db, 0o600)
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise CheckpointError("checkpoint 已损坏")
        with connection:
            saver = SqliteSaver(connection)
            from contextlib import ExitStack

            with ExitStack() as stack:
                graph = build_workflow(
                    mode=mode,
                    checkpointer=saver,
                    emit=emit,
                    local_scope=local_scope,
                    stack=stack,
                )
                yield graph
    except sqlite3.DatabaseError as exc:
        raise CheckpointError("checkpoint 无法读取或已损坏") from exc
    finally:
        connection.close()


def snapshot(graph, config: dict) -> dict:
    state = graph.get_state(config)
    values = state.values or {}
    messages = values.get("messages", [])
    last_calls = next(
        (
            m.tool_calls
            for m in reversed(messages)
            if isinstance(m, AIMessage) and m.tool_calls
        ),
        [],
    )
    unused_calls = list(last_calls)
    pending = []
    local_requests = []
    images = []
    for m in messages:
        if isinstance(m, ToolMessage) and isinstance(m.artifact, dict):
            images.extend(m.artifact.get("images", []))
    for task in state.tasks:
        for interrupt in task.interrupts:
            if interrupt.value.get("kind") == "local_operation":
                local_requests.append({**interrupt.value, "interrupt_id": interrupt.id})
                continue
            for index, action in enumerate(interrupt.value.get("action_requests", [])):
                candidates = [
                    c
                    for c in unused_calls
                    if c["name"] == action["name"] and c["args"] == action["args"]
                ]
                source_id = (
                    candidates[0]["id"] if candidates else f"{interrupt.id}:{index}"
                )
                if candidates:
                    unused_calls.remove(candidates[0])
                pending.append(
                    {
                        "interrupt_id": interrupt.id,
                        "index": index,
                        "source_id": source_id,
                        "action": action,
                    }
                )
    subtasks = {}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call["name"] == "task":
                    subtasks[call["id"]] = {
                        "call_id": call["id"],
                        "role": call["args"].get("subagent_type", ""),
                        "description": call["args"].get("description", "")[:8000],
                        "state": "interrupted",
                        "result": "",
                    }
        elif isinstance(message, ToolMessage) and message.tool_call_id in subtasks:
            subtasks[message.tool_call_id].update(
                state="failed" if message.status == "error" else "completed",
                result=str(message.content)[:16000],
            )
    result = next(
        (
            m.text
            for m in reversed(messages)
            if isinstance(m, AIMessage) and not m.tool_calls
        ),
        "",
    )
    return {
        "checkpoint_id": (state.config or {})
        .get("configurable", {})
        .get("checkpoint_id", ""),
        "plan": values.get("todos", []),
        "documents": values.get("documents", {}),
        "images": images,
        "pending": pending,
        "subtasks": list(subtasks.values()),
        "local_requests": local_requests,
        "complete": not state.next
        and not pending
        and not local_requests
        and bool(result),
        "result": result[:32000],
    }


def inspect_checkpoint(attempt) -> dict:
    """仅读取图状态使用固定模型，不访问供应商；与执行配置兼容性独立检查。"""
    frozen = attempt.input_snapshot.get("workflow", {})
    if attempt.workflow_version != VERSION or frozen != execution_config(attempt.mode):
        raise CheckpointError("执行版本或模型配置不兼容")
    directory = checkpoint_dir(attempt.pk)
    if not (directory / "checkpoint.sqlite3").is_file():
        raise CheckpointError("该执行没有可恢复的 checkpoint")
    # inspect 不创建状态，也不运行图；避免读取历史时要求供应商 API Key。
    with open_graph(
        directory,
        mode="demo",
        action="inspect",
        frozen=execution_config("demo"),
        local_scope=attempt.input_snapshot.get("device"),
    ) as graph:
        data = snapshot(graph, {"configurable": {"thread_id": str(attempt.pk)}})
        if not data["checkpoint_id"]:
            raise CheckpointError("checkpoint 没有有效图状态，不能恢复")
        return data


def _run_workflow(payload: dict, emit) -> dict:
    config = {
        "configurable": {"thread_id": payload["attempt_id"]},
        "recursion_limit": 48,
    }
    action = payload["action"]
    with open_graph(
        payload["checkpoint_dir"],
        mode=payload["mode"],
        action=action,
        frozen=payload["snapshot"]["workflow"],
        emit=emit,
        local_scope=payload["snapshot"].get("device"),
    ) as graph:
        if action == "start":
            if graph.get_state(config).values:
                raise CheckpointError("已有 checkpoint，拒绝从头覆盖执行")
            data = {
                "messages": [
                    {
                        "role": "user",
                        "content": payload["snapshot"]["title"]
                        + "\n"
                        + payload["snapshot"]["description"],
                    }
                ],
                "documents": {},
            }
        elif payload.get("decisions"):
            data = Command(resume=payload["decisions"])
        else:
            data = None
        # 子图 namespace 只作为展示关联；工具调用 ID 来自角色中间件。
        for namespace, update in graph.stream(
            data, config=config, stream_mode="updates", subgraphs=True
        ):
            if namespace:
                from .policy import PARENT_CALL

                emit(
                    "subgraph",
                    {
                        "namespace": "/".join(namespace)[:300],
                        "parent_call_id": PARENT_CALL.get(),
                    },
                )
        return snapshot(graph, config)


def run_workflow(payload, emit):
    marker = CURRENT.set(
        {
            "snapshot": payload["snapshot"],
            "root": payload.get("local_root"),
            "authorizations": payload.get("local_authorizations"),
            "directory": str(Path(payload["checkpoint_dir"]) / "images"),
        }
    )
    try:
        return _run_workflow(payload, emit)
    finally:
        CURRENT.reset(marker)
