"""独立本机 DeepAgents 执行器；任务只包含数据，子进程入口固定。"""

import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from .config import load, save
from .agent import manifest, request
from .job_transport import Heartbeat, init_events, flush_events, event, deliver, redact


def model_environment(root):
    config = (
        json.loads((root / "model.json").read_text())
        if (root / "model.json").exists()
        else {}
    )
    return config


def profiles(root, config):
    from personal_superagent.workflow_v06.checkpoints import execution_config

    model = model_environment(root)
    previous = {k: os.environ.get(k) for k in model}
    os.environ.update(model)
    try:
        modes = ["demo"] + (
            ["real"]
            if (root / "model-ready.json").exists()
            and json.loads((root / "model-ready.json").read_text()).get("fingerprint")
            == __import__("hashlib")
            .sha256(json.dumps(model, sort_keys=True).encode())
            .hexdigest()
            else []
        )
        configs = {mode: execution_config(mode) for mode in modes}
        from personal_superagent.collaboration.toolkit import capabilities

        available = capabilities()
        result = []
        for role in ["writer", "reviewer", "researcher", "image_designer"]:
            for scope in [None, *config["roots"]]:
                tools = ["inspect_context", "add_numbers", "text_statistics"]
                if scope:
                    tools += ["local_" + t for t in scope["tools"]]
                if role == "researcher":
                    if available["tavily_search"]:
                        tools.append("tavily_search")
                    for c in json.loads(model.get("MCP_CONFIG", "[]")):
                        tools += ["mcp__" + n for n in c["allowed_tools"]]
                if role == "image_designer" and available["generate_image"]:
                    tools.append("generate_image")
                result.append(
                    {
                        "role": role,
                        "grant_id": scope["id"] if scope else "",
                        "tools": tools,
                        "modes": modes,
                        "model_config": configs,
                    }
                )
        return result
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def configure_model(root, verify=False):
    import getpass, hashlib

    if verify:
        cfg = model_environment(root)
        os.environ.update(cfg)
        from personal_superagent.intake.management.commands.model_check import Command

        # 使用隔离环境变量/状态目录，凭证绝不写入服务器。
        os.environ["AGENT_RUNTIME_DIR"] = str(root / "model-check")
        Command().handle()
        (root / "model-ready.json").write_text(
            json.dumps(
                {
                    "fingerprint": hashlib.sha256(
                        json.dumps(cfg, sort_keys=True).encode()
                    ).hexdigest()
                }
            )
        )
        os.chmod(root / "model-ready.json", 0o600)
        return
    from urllib.parse import urlsplit

    name = input("本机模型名称：").strip()
    base = input("模型 Base URL（可为本机 HTTP）：").strip()
    key = getpass.getpass("本机独立 API Key（隐藏，本地无鉴权服务填 local）：").strip()
    u = urlsplit(base)
    if base and (
        u.username
        or u.password
        or not (
            u.scheme == "https"
            or (u.scheme == "http" and u.hostname in {"127.0.0.1", "localhost"})
        )
    ):
        raise ValueError("模型地址无效")
    if not name or not key or any("\n" in s for s in [name, base, key]):
        raise ValueError("模型配置无效")
    path = root / "model.json"
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"MODEL_NAME": name, "MODEL_BASE_URL": base, "MODEL_API_KEY": key}, f)
    print("本机模型配置已保存，请显式执行 agent-check 验证（两次付费模型请求）。")


def run(root, once=False):
    import fcntl

    lock = (root / "agent.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    db = sqlite3.connect(root / "agent-ledger.sqlite3")
    os.chmod(root / "agent-ledger.sqlite3", 0o600)
    db.execute(
        "CREATE TABLE IF NOT EXISTS jobs(token TEXT PRIMARY KEY, payload TEXT, result TEXT, pid INTEGER,birth REAL)"
    )
    db.commit()
    init_events(db)
    while True:
        config = load(root)
        save(root, config)
        request(
            config,
            "agent-hello",
            {"profiles": profiles(root, config), "grants": manifest(config)},
        )
        # 先报告已完成回执；started 崩溃只核验进程退出，不重放 graph。
        import psutil

        for token, payload, result, pid, birth in db.execute(
            "SELECT * FROM jobs"
        ).fetchall():
            job = json.loads(payload)
            flush_events(db, config, token)
            if result:
                deliver(root, config, job, json.loads(result))
                db.execute("DELETE FROM jobs WHERE token=?", (token,))
                db.commit()
                continue
            alive = False
            if pid:
                try:
                    alive = (
                        psutil.Process(pid).create_time() == birth
                        and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
                    )
                except psutil.NoSuchProcess:
                    pass
            if alive:
                raise ValueError("旧执行仍在运行，拒绝重复启动")
            result = {
                "state": "interrupted",
                "error": "本机执行曾开始后异常退出，副作用待核实；未重放",
            }
            request(
                config,
                "agent-control",
                {"id": job["id"], "token": token, "action": "result", "result": result},
            )
            db.execute("DELETE FROM jobs WHERE token=?", (token,))
            db.commit()
        response = request(config, "agent-claim", {})
        job = response["job"]
        if job:
            token = job["token"]
            db.execute(
                "INSERT INTO jobs VALUES (?,?,NULL,NULL,NULL)", (token, json.dumps(job))
            )
            db.commit()
            directory = root / "runs" / job["id"]
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            payload = {
                "attempt_id": job["id"],
                "mode": job["mode"],
                "snapshot": job["snapshot"],
                "workflow_version": "0.6.0",
                "action": job["action"],
                "decisions": job["decisions"],
                "checkpoint_dir": str(directory),
                "local_authorizations": str(root / "grants.json"),
            }
            scope = job["snapshot"].get("device")
            if scope:
                item = next(
                    (r for r in config["roots"] if r["id"] == str(scope["grant_id"])),
                    None,
                )
                if (
                    not item
                    or not set(scope["tools"]) <= set(item["tools"])
                    or root.resolve().is_relative_to(Path(item["path"]).resolve())
                ):
                    raise ValueError("本机授权变化，拒绝执行")
                payload["local_root"] = {**item, "tools": scope["tools"]}
            env = {
                k: v
                for k, v in os.environ.items()
                if k in {"PATH", "LANG", "SYSTEMROOT", "SSL_CERT_FILE"}
            }
            env.update(model_environment(root))
            env["LANGSMITH_TRACING"] = "false"
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "personal_superagent.execution.child",
                    job["id"],
                    token,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            db.execute(
                "UPDATE jobs SET pid=?,birth=? WHERE token=?",
                (process.pid, psutil.Process(process.pid).create_time(), token),
            )
            db.commit()
            process.stdin.write((json.dumps(payload) + "\n").encode())
            process.stdin.flush()
            items = queue.Queue()

            def read():
                for line in iter(process.stdout.readline, b""):
                    try:
                        items.put(json.loads(line))
                    except ValueError:
                        items.put({"kind": "error", "data": {}})
                items.put(None)

            threading.Thread(target=read, daemon=True).start()
            result = {"state": "failed", "error": "本机 Agent 未交付结果"}
            sequence = 0
            guardian = Heartbeat(root, job, process)
            guardian.__enter__()
            try:
                while True:
                    if guardian.denied:
                        result = {
                            "state": "interrupted",
                            "error": "许可失效、离线或超时；本机进程已终止",
                        }
                        break
                    try:
                        item = items.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if item is None:
                        break
                    if item["kind"] == "snapshot":
                        result = {"state": "succeeded", "snapshot": item["data"]}
                    elif item["kind"] == "error":
                        result = {
                            "state": "failed",
                            "error": "本机模型、工具或 checkpoint 执行失败",
                        }
                    elif item["kind"] in {
                        "model",
                        "plan",
                        "tool_start",
                        "tool_end",
                        "subagent_start",
                        "subagent_end",
                        "subgraph",
                    }:
                        sequence += 1
                        event(
                            db,
                            config,
                            token,
                            sequence,
                            {
                                "id": job["id"],
                                "token": token,
                                "action": "event",
                                "sequence": sequence,
                                "kind": item["kind"],
                                "data": redact(root, item["data"]),
                            },
                        )
                process.wait(timeout=5)
                if process.returncode:
                    result = {"state": "failed", "error": "本机子进程异常退出"}
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                process.stdin.close()
                process.stdout.close()
                if __import__("sys").exc_info()[0] is not None:
                    guardian.__exit__()
            # 确定结果先落盘，再上传图片和回执；回执丢失只重发。
            result = redact(root, result)
            db.execute(
                "UPDATE jobs SET result=? WHERE token=?", (json.dumps(result), token)
            )
            db.commit()
            try:
                deliver(root, config, job, result)
            finally:
                guardian.__exit__()
            db.execute("DELETE FROM jobs WHERE token=?", (token,))
            db.commit()
        if once:
            return
        time.sleep(2)
