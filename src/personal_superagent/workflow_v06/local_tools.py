"""本机 Agent 直接使用固定文件工具；写入仍由图原生审批暂停。"""

from langchain_core.tools import tool
from personal_superagent.client.files import execute


def build_local_tools(scope):
    from .context import CURRENT

    root = CURRENT.get().get("root")
    if not scope:
        return []
    if not root:
        from personal_superagent.workflow.local_tools import build_local_tools as remote

        return remote(scope)

    def checked(name):
        import json
        from pathlib import Path

        file = CURRENT.get().get("authorizations")
        if file:
            grants = json.loads(Path(file).read_text())
            match = next((g for g in grants if g["id"] == scope["grant_id"]), None)
            if not match or name not in match["tools"] or match["path"] != root["path"]:
                raise ValueError("本机目录或工具授权已撤销")
        return root

    @tool
    def local_list_files(path: str = ".") -> dict:
        """列出授权目录中当前层文件。"""
        return execute(checked("list_files"), "list_files", {"path": path})

    @tool
    def local_read_text(path: str) -> dict:
        """读取授权目录中的 UTF-8 文本。"""
        return execute(checked("read_text"), "read_text", {"path": path})

    @tool
    def local_write_text(path: str, content: str) -> dict:
        """经用户批准后新建文本，不覆盖已有文件。"""
        return execute(
            checked("write_text"), "write_text", {"path": path, "content": content}
        )

    return [
        t
        for t in [local_list_files, local_read_text, local_write_text]
        if t.name.removeprefix("local_") in scope["tools"]
    ]
