import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import load
from .ledger import Ledger


def request(config, endpoint, data):
    data = {**data, "protocol": 1}
    headers = {"Content-Type": "application/json"}
    if config.get("token"):
        headers["Authorization"] = "Bearer " + config["token"]
    req = Request(
        config["url"] + "/api/device/" + endpoint + "/",
        json.dumps(data).encode(),
        headers,
    )
    with urlopen(req, timeout=15) as response:
        return json.load(response)


def manifest(config):
    return [
        {"id": r["id"], "label": r["label"], "tools": r["tools"]}
        for r in config["roots"]
    ]


def execute_operation(config, session, operation, ledger, client_dir=None):
    old = ledger.begin(operation)
    if old:
        return old
    process = None
    try:
        root = next(
            (r for r in config["roots"] if r["id"] == operation["grant_id"]), None
        )
        if root is None or operation["tool"] not in root["tools"]:
            raise ValueError("本地授权已经撤销")
        if client_dir and Path(client_dir).resolve().is_relative_to(Path(root["path"])):
            raise ValueError("工具不能访问客户端凭证目录")
        request(
            config,
            "check",
            {"session": session, "id": operation["id"], "lease": operation["lease"]},
        )
        process = subprocess.Popen(
            [sys.executable, "-m", "personal_superagent.client.tool_process"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={
                k: v
                for k, v in os.environ.items()
                if k in {"PATH", "LANG", "SYSTEMROOT"}
            },
        )
        try:
            output, _ = process.communicate(
                json.dumps(
                    {
                        "root": root,
                        "tool": operation["tool"],
                        "arguments": operation["arguments"],
                    }
                ).encode()
                + b"\n",
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return "uncertain", {"error": "本地工具超时，操作可能已生效，不会自动重放"}
        if process.returncode or len(output) > 300000:
            return "uncertain", {"error": "本地工具进程异常，结果待核实"}
        result = json.loads(output)
        return (
            ("succeeded", result["data"])
            if result["ok"]
            else ("failed", {"error": result["error"]})
        )
    except (ValueError, HTTPError, OSError):
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.communicate()
            return "uncertain", {"error": "工具启动后异常，操作结果待核实；不会重放"}
        return "failed", {"error": "本地授权、云端许可或连接校验失败；操作未开始"}


def run(root, *, once=False):
    if os.name != "posix":
        raise ValueError("原生 Windows 请改在 WSL2 中运行客户端")
    import fcntl

    lock = (root / "run.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError("该客户端目录已有运行实例") from None
    session = str(uuid.uuid4())
    ledger = Ledger(root / "operations.sqlite3")
    connected = False
    print("客户端已启动；目录内容会按授权发送到云端及模型。Ctrl+C 停止。", flush=True)
    while True:
        config = load(root)
        try:
            response = request(
                config,
                "connect" if not connected else "poll",
                {"session": session, "grants": manifest(config)},
            )
            connected = True
            # 已完成但回执丢失的操作只重发结果；started 的旧操作只报告未知。
            for operation, state, result in ledger.pending():
                request(
                    config,
                    "report",
                    {
                        "session": session,
                        "id": operation["id"],
                        "lease": operation["lease"],
                        "state": state,
                        "result": result,
                    },
                )
                ledger.reported(operation)
            operation = response["operation"]
            if operation:
                state, result = execute_operation(
                    load(root), session, operation, ledger, client_dir=root
                )
                ledger.complete(operation, state, result)
                request(
                    config,
                    "report",
                    {
                        "session": session,
                        "id": operation["id"],
                        "lease": operation["lease"],
                        "state": state,
                        "result": result,
                    },
                )
                ledger.reported(operation)
                print("操作 " + operation["tool"] + "：" + state, flush=True)
            if once:
                break
            time.sleep(2)
        except HTTPError as exc:
            if exc.code in {400, 401, 403}:
                raise ValueError(
                    "设备授权或会话已失效，请在网页检查；未打印凭证。"
                ) from None
            if once:
                raise ValueError("服务器暂时不可用") from None
            time.sleep(2)
        except (URLError, TimeoutError):
            if once:
                raise ValueError("无法连接服务器") from None
            time.sleep(2)
