"""Python 管领取/账本，TypeScript 管 Claude；密钥和仓库路径不进入云端快照。"""

import json
import os
import queue
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path
import psutil
from personal_superagent.client.agent import request
from personal_superagent.client.config import load as load_config
from . import repositories
from .ledger import Ledger

EXECUTOR = Path(__file__).resolve().parents[4] / "executor" / "dist" / "main.js"


def check(root):
    if not EXECUTOR.is_file():
        raise ValueError(
            "先运行 npm ci --prefix executor && npm run build --prefix executor"
        )
    try:
        result = subprocess.run(
            ["claude", "auth", "status"], capture_output=True, timeout=15
        )
    except subprocess.TimeoutExpired:
        raise ValueError(
            "Claude 登录状态检查超时；请先在普通终端运行 claude auth status 排查"
        ) from None
    try:
        ready = (
            result.returncode == 0 and json.loads(result.stdout).get("loggedIn") is True
        )
    except (ValueError, TypeError):
        ready = False
    if not ready:
        raise ValueError(
            "Claude 尚未登录；请在本机终端执行 claude auth login，再运行 happier-check"
        )
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            "import('@anthropic-ai/claude-agent-sdk').then(m=>{if(typeof m.query!=='function')process.exit(1)})",
        ],
        cwd=EXECUTOR.parent.parent,
        check=True,
        capture_output=True,
        timeout=15,
    )
    return True


def control(config, job, action, **data):
    return request(
        config,
        "happier-control",
        {
            "id": job["id"],
            "token": job["token"],
            "instance": job["instance"],
            "action": action,
            **data,
        },
    )


def stop(process):
    """进程组清空后才确认停止；主进程退出不代表 CLI/Shell 子孙已退出。"""
    if getattr(process, "_workbench_stopped", False):
        return

    def members():
        items = []
        for item in psutil.process_iter(["pid", "status"]):
            try:
                if (
                    os.getpgid(item.pid) == process.pid
                    and item.status() != psutil.STATUS_ZOMBIE
                ):
                    items.append(item)
            except (ProcessLookupError, psutil.NoSuchProcess):
                pass
        return items

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait(timeout=4)
        process._workbench_stopped = True
        return
    try:
        process.wait(timeout=4)
    except subprocess.TimeoutExpired:
        pass
    deadline = time.monotonic() + 4
    while members() and time.monotonic() < deadline:
        time.sleep(0.05)
    if members():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 4
        while members() and time.monotonic() < deadline:
            time.sleep(0.05)
    if members():
        raise ValueError("旧进程组尚未停止，保留领取归属，请人工核查")
    process.wait(timeout=4)
    process._workbench_stopped = True


def upload(config, ledger, job):
    cursor = ledger.db.execute(
        "select seq from cursors where job=?", (job["id"],)
    ).fetchone()
    for seq, event in ledger.db.execute(
        "select sequence,event from events where job=? and sequence>? order by sequence",
        (job["id"], cursor[0] if cursor else 0),
    ).fetchall():
        control(config, job, "event", sequence=seq, event=json.loads(event))
        ledger.db.execute(
            "insert or replace into cursors values(?,?)", (job["id"], seq)
        )
        ledger.db.commit()


def execute(root, config, ledger, job):
    ledger.begin(job)  # 必须先持久化启动意图；不对启动失败自动重试。
    process = None
    checker = None
    result = {"state": "failed", "error": "本机执行未完成"}
    path = None
    try:
        repo = repositories.resolve_repository(root, job["snapshot"])
        path, branch = repositories.prepare(root, job)
        policy = job["snapshot"]["policy"]
        env = {
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "HOME", "LANG", "TMPDIR", "SHELL", "SYSTEMROOT"}
        }
        env["WORKBENCH_RUN_INSTANCE"] = job["instance"]
        # 凭据由本机 Claude 登录管理；云端不下发 env、可执行程序路径或启动参数。
        process = subprocess.Popen(
            ["node", str(EXECUTOR), job["instance"]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
            start_new_session=True,
        )
        ledger.process(
            job["id"], process.pid, psutil.Process(process.pid).create_time()
        )

        def send(data):
            process.stdin.write(json.dumps({"protocol": 1, **data}) + "\n")
            process.stdin.flush()

        send(
            {
                "action": "start",
                "cwd": str(path),
                "prompt": job["snapshot"]["description"]
                + "\n前置任务交付："
                + json.dumps(job["snapshot"].get("context", []), ensure_ascii=False),
                "write_paths": policy["write_paths"],
                "checks": policy["checks"],
                "max_turns": policy["max_turns"],
            }
        )
        events = queue.Queue()

        def reader():
            for line in process.stdout:
                if len(line) > 2000000:
                    events.put(
                        {"kind": "result", "state": "failed", "error": "执行事件过大"}
                    )
                    return
                try:
                    events.put(json.loads(line))
                except ValueError:
                    events.put(
                        {"kind": "result", "state": "failed", "error": "执行协议无效"}
                    )
                    return

        threading.Thread(target=reader, daemon=True).start()
        start = time.monotonic()
        last_heartbeat = 0
        sent = set()
        terminal = None
        while time.monotonic() - start < policy["timeout"]:
            # 每轮重读本机授权，撤销不会等到新任务才生效。
            repositories.resolve_repository(root, job["snapshot"])
            if time.monotonic() - last_heartbeat > 3:
                response = control(config, job, "heartbeat")
                last_heartbeat = time.monotonic()
                if not response["continue"]:
                    result = {
                        "state": "interrupted",
                        "error": "执行取消、授权改变或领取失效",
                    }
                    break
                for d in response["decisions"]:
                    if d["request_id"] not in sent:
                        send({"action": "respond", **d})
                        sent.add(d["request_id"])
                upload(config, ledger, job)
            try:
                event = events.get(timeout=0.2)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            if event["kind"] == "result":
                terminal = event
                break
            if event["kind"] in {
                "session",
                "text",
                "tool_start",
                "tool_end",
                "permission",
                "permission_applied",
                "activity",
            }:
                event = json.loads(
                    json.dumps(event)
                    .replace(str(path), "[worktree]")
                    .replace(repo["path"], "[repository]")
                    .replace(str(root), "[client]")
                )
                ledger.event(job["id"], event)
        else:
            result = {"state": "interrupted", "error": "任务超时，未自动重试"}
        stop(process)
        upload(config, ledger, job)
        if terminal:
            result = {
                k: v for k, v in terminal.items() if k not in {"protocol", "kind"}
            }
            if result["state"] == "succeeded":
                checks = []
                for command in policy["checks"]:
                    checker = subprocess.Popen(
                        shlex.split(command),
                        cwd=path,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        env={
                            **env,
                            "GIT_CONFIG_NOSYSTEM": "1",
                            "GIT_CONFIG_GLOBAL": os.devnull,
                        },
                    )
                    ledger.process(
                        job["id"],
                        checker.pid,
                        psutil.Process(checker.pid).create_time(),
                    )
                    tail = bytearray()

                    def drain(stream, buffer):
                        try:
                            while data := stream.read(4096):
                                buffer.extend(data)
                                del buffer[:-20000]
                        finally:
                            stream.close()

                    log_reader = threading.Thread(
                        target=drain, args=(checker.stdout, tail), daemon=True
                    )
                    log_reader.start()
                    timed_out = False
                    check_start = time.monotonic()
                    while True:
                        try:
                            checker.wait(timeout=1)
                            break
                        except subprocess.TimeoutExpired:
                            if (
                                time.monotonic() - check_start > 120
                                or time.monotonic() - start > policy["timeout"]
                            ):
                                stop(checker)
                                timed_out = True
                                break
                            if time.monotonic() - last_heartbeat > 3:
                                if not control(config, job, "heartbeat")["continue"]:
                                    stop(checker)
                                    raise ValueError("检查中取消或失联")
                                last_heartbeat = time.monotonic()
                    stop(checker)
                    log_reader.join(timeout=2)
                    output = bytes(tail) if not timed_out else b"check timed out"
                    checks.append(
                        {
                            "command": command,
                            "exit_code": 124 if timed_out else checker.returncode,
                            "output": output.decode(errors="replace")[-20000:],
                        }
                    )
                    ledger.event(job["id"], {"kind": "check", **checks[-1]})
                    control(config, job, "heartbeat")
                result["checks"] = checks
        if not terminal and result.get("error") == "本机执行未完成":
            result = {"state": "failed", "error": "Claude 未返回明确终态"}
        if path:
            result.update(repositories.collect(path, policy))
            result["branch"] = branch
    except (ValueError, OSError, subprocess.SubprocessError, KeyError):
        result = {
            "state": "interrupted",
            "error": "本机配置、网络或执行异常；请检查工作区，不自动重放",
        }
    finally:
        if process:
            stop(process)
        if checker:
            stop(checker)
        ledger.finish(job["id"], result)
    upload(config, ledger, job)
    control(config, job, "result", report=result)
    ledger.ack(job["id"])


def recover(config, ledger):
    for id, payload, pid, birth, result in ledger.unfinished():
        job = json.loads(payload)
        if result is None:
            if pid and psutil.pid_exists(pid):
                p = psutil.Process(pid)
                if abs(p.create_time() - birth) < 0.01:
                    # 仅在实例参数和进程组均匹配时停止旧受管运行；不能凭 PID 猜测。
                    if (
                        p.environ().get("WORKBENCH_RUN_INSTANCE") != job["instance"]
                        or os.getpgid(pid) != pid
                    ):
                        raise ValueError("无法确认旧进程归属，请人工核查")
                    os.killpg(pid, signal.SIGTERM)
                    try:
                        p.wait(timeout=4)
                    except psutil.TimeoutExpired:
                        raise ValueError("旧进程尚未停止，请人工核查")
            if pid:
                members = []
                for candidate in psutil.process_iter(["pid", "create_time", "status"]):
                    try:
                        if (
                            os.getpgid(candidate.pid) == pid
                            and candidate.status() != psutil.STATUS_ZOMBIE
                        ):
                            if (
                                candidate.create_time() < birth
                                or candidate.environ().get("WORKBENCH_RUN_INSTANCE")
                                != job["instance"]
                            ):
                                raise ValueError("旧进程组归属未知，请人工核查")
                            members.append(candidate)
                    except (ProcessLookupError, psutil.NoSuchProcess):
                        pass
                if members:
                    os.killpg(pid, signal.SIGTERM)
                    _, remaining = psutil.wait_procs(members, timeout=4)
                    if remaining:
                        raise ValueError("旧子进程尚未停止，请人工核查")
            result = json.dumps(
                {"state": "interrupted", "error": "客户端重启；旧执行已停止，未重放"}
            )
            ledger.finish(id, json.loads(result))
        # 已失效租约的未上传展示事件无需复活；结果回执仍用于确认旧进程停止。
        try:
            upload(config, ledger, job)
        except Exception:
            pass
        control(config, job, "result", report=json.loads(result))
        ledger.ack(id)


def run(root, once=False):
    check(root)
    config = load_config(root)
    ledger = Ledger(root)
    try:
        recover(config, ledger)
        while True:
            request(
                config,
                "happier-hello",
                {"repositories": repositories.manifest(root), "ready": True},
            )
            job = request(config, "happier-claim", {})["job"]
            if job:
                execute(root, config, ledger, job)
            if once:
                return
            time.sleep(2)
    finally:
        ledger.db.close()
