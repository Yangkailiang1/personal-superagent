"""POSIX/WSL2 文件工具：目录 FD 锚定、每层 O_NOFOLLOW，不把路径隔离当沙箱。"""

import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

TOOLS = {"list_files", "read_text", "write_text"}
LIMIT = 65536


def parts(path: str) -> tuple[str, ...]:
    if not isinstance(path, str) or "\x00" in path or "\\" in path:
        raise ValueError("路径格式不合法")
    item = PurePosixPath(path)
    if item.is_absolute() or ".." in item.parts:
        raise ValueError("拒绝绝对路径和目录越界")
    return item.parts


def describe_root(path: str) -> dict:
    if os.name != "posix":
        raise ValueError("本版客户端支持 macOS、Linux 和 WSL2；不支持原生 Windows")
    root = Path(path).expanduser().resolve(strict=True)
    info = root.stat()
    if not root.is_dir():
        raise ValueError("授权根必须是目录")
    return {"path": str(root), "dev": info.st_dev, "ino": info.st_ino}


@contextmanager
def directory(root: dict, components: tuple[str, ...]):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for component in Path(root["path"]).parts[1:]:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (root["dev"], root["ino"]):
            raise ValueError("授权根已替换，请重新授权")
        for component in components:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def execute(root: dict, tool: str, arguments: dict) -> dict:
    if tool not in root["tools"] or tool not in TOOLS:
        raise ValueError("本地没有授权该工具")
    path_parts = parts(arguments.get("path", "."))
    if tool == "list_files":
        with directory(root, path_parts) as fd:
            names = sorted(os.listdir(fd))
            return {"entries": names[:200], "truncated": len(names) > 200}
    if not path_parts:
        raise ValueError("必须指定文件")
    with directory(root, path_parts[:-1]) as fd:
        name = path_parts[-1]
        if tool == "read_text":
            file_fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
            )
            try:
                if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                    raise ValueError("只能读取普通文本文件")
                content = b""
                while len(content) <= LIMIT:
                    block = os.read(file_fd, min(8192, LIMIT + 1 - len(content)))
                    if not block:
                        break
                    content += block
                if len(content) > LIMIT:
                    raise ValueError("文本超过 64 KiB，请缩小文件")
                return {"text": content.decode("utf-8")}
            finally:
                os.close(file_fd)
        content = arguments.get("content", "")
        if not isinstance(content, str) or len(content.encode()) > LIMIT:
            raise ValueError("写入文本超过 64 KiB")
        temporary = ".superagent-" + uuid.uuid4().hex
        temp_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=fd,
        )
        try:
            with os.fdopen(temp_fd, "wb") as file:
                file.write(content.encode())
                file.flush()
                os.fsync(file.fileno())
            # 原子发布且绝不覆盖；链接后若进程崩溃则标结果不确定，不自动重放。
            os.link(
                temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False
            )
            os.fsync(fd)
            return {"path": arguments["path"], "created": True}
        finally:
            os.unlink(temporary, dir_fd=fd)
