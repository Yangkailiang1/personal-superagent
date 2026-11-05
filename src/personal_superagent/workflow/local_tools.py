"""工具只产生原生 interrupt；子进程不接触设备 token 或业务数据库。"""

import json

from langchain.tools import ToolRuntime, tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field


class PathInput(BaseModel):
    path: str = Field(min_length=1, max_length=200)


class WriteInput(PathInput):
    content: str = Field(max_length=12000)


def build_local_tools(scope):
    if not scope:
        return []

    def call(name, arguments, runtime):
        result = interrupt(
            {
                "kind": "local_operation",
                "tool": name,
                "arguments": arguments,
                "grant_id": scope["grant_id"],
                "source_id": runtime.tool_call_id,
            }
        )
        if result.get("state") != "succeeded":
            raise ValueError(
                str(result.get("result", {}).get("error", "本地工具未完成"))
            )
        return json.dumps(result["result"], ensure_ascii=False)

    @tool(args_schema=PathInput)
    def local_list_files(path: str, runtime: ToolRuntime) -> str:
        """列出本次已授权目录下的相对路径；需要用户设备在线。"""
        return call("list_files", {"path": path}, runtime)

    @tool(args_schema=PathInput)
    def local_read_text(path: str, runtime: ToolRuntime) -> str:
        """读取已授权目录下 UTF-8 文本，最多 64 KiB；内容会进入云端模型。"""
        return call("read_text", {"path": path}, runtime)

    @tool(args_schema=WriteInput)
    def local_write_text(path: str, content: str, runtime: ToolRuntime) -> str:
        """申请在授权目录新建文本文件，必须人工批准；不覆盖已有文件。"""
        return call("write_text", {"path": path, "content": content}, runtime)

    return [
        t
        for t in [local_list_files, local_read_text, local_write_text]
        if t.name.removeprefix("local_") in scope["tools"]
    ]
