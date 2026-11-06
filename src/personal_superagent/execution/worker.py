"""Worker 监督子进程，模型执行永远不占用领取事务。"""
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field

import psutil
from django.db import close_old_connections, transaction

from personal_superagent.tasks.models import Task
from .claims import claim_next, expire_leases, heartbeat, require_postgres
from .lifecycle import complete, record_event
from .models import Attempt
from .processes import reconcile_interrupted


@dataclass
class Running:
    attempt: Attempt
    process: subprocess.Popen
    started: float = field(default_factory=time.monotonic)
    messages: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=100))
    result: str = ""
    error: str = ""
    eof: bool = False
    snapshot: dict | None = None


def read_protocol(running: Running) -> None:
    try:
        while line := running.process.stdout.readline(262145):
            if len(line) > 262144:
                running.messages.put({"kind": "error", "data": {"code": "OutputLimit"}})
                break
            try:
                item = json.loads(line)
                if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
                    raise ValueError
                running.messages.put(item)
            except (ValueError, UnicodeError):
                running.messages.put({"kind": "error", "data": {"code": "InvalidProtocol"}})
                break
    finally:
        running.messages.put(None)


def child_environment() -> dict[str, str]:
    """不把数据库密码、Django 密钥或宿主供应商凭据传给 Agent 子进程。"""
    names = ["PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR", "SSL_CERT_FILE",
             "MODEL_API_KEY", "MODEL_NAME", "MODEL_BASE_URL", "TAVILY_API_KEY", "IMAGE_API_KEY", "IMAGE_BASE_URL", "IMAGE_MODEL_NAME", "MCP_CONFIG", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"]
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(PYTHONUNBUFFERED="1", LANGSMITH_TRACING="false")
    return env


def redact(text: str) -> str:
    for name in ["MODEL_API_KEY", "TAVILY_API_KEY", "IMAGE_API_KEY", "PGPASSWORD", "DJANGO_SECRET_KEY"]:
        secret = os.environ.get(name)
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def terminate(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def spawn(attempt: Attempt) -> Running | None:
    if not heartbeat(attempt.pk, attempt.claim_token):
        return None
    process = subprocess.Popen(
        [sys.executable, "-m", "personal_superagent.execution.child", str(attempt.pk), str(attempt.claim_token)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=child_environment(), start_new_session=True,
    )
    try:
        # 登记后才把输入交给子进程。若此刻租约已失效，绝不能开始模型执行。
        with transaction.atomic():
            Task.objects.select_for_update().get(pk=attempt.task_id)
            current = Attempt.objects.select_for_update().get(pk=attempt.pk)
            current.process_id = process.pid
            current.process_birth = psutil.Process(process.pid).create_time()
            current.save(update_fields=["process_id", "process_birth"])
            if current.state != "running" or current.claim_token != attempt.claim_token:
                terminate(process)
                return None
        from personal_superagent.workflow.checkpoints import checkpoint_dir
        decisions = {}
        for approval in attempt.approvals.filter(checkpoint_id=attempt.checkpoint_id).order_by("interrupt_id", "action_index"):
            if approval.decision in {"approve", "reject"}:
                decisions.setdefault(approval.interrupt_id, {"decisions": []})["decisions"].append({"type": approval.decision})
        for operation in attempt.local_operations.filter(checkpoint_id=attempt.checkpoint_id, state__in=["succeeded", "failed"]):
            decisions[operation.interrupt_id] = {"state": operation.state, "result": operation.result}
        payload = {
            "snapshot": attempt.input_snapshot, "mode": attempt.mode, "workflow_version": attempt.workflow_version,
            "attempt_id": str(attempt.pk), "action": attempt.execution_action,
            "checkpoint_dir": str(checkpoint_dir(attempt.pk)), "decisions": decisions if attempt.execution_action == "resume" else {},
        }
        process.stdin.write((json.dumps(payload) + "\n").encode())
        process.stdin.flush()
        running = Running(attempt, process)
        threading.Thread(target=read_protocol, args=[running], daemon=True).start()
        return running
    except BaseException:
        terminate(process)
        raise


def consume(running: Running) -> None:
    # 限制每轮消费条数，避免高频事件让其他任务的心跳饥饿。
    for _ in range(100):
        try:
            item = running.messages.get_nowait()
        except queue.Empty:
            return
        if item is None:
            running.eof = True
            return
        kind, data = item.get("kind"), item["data"]
        if kind == "result":
            running.result = redact(str(data.get("text", "")))[:32000]
        elif kind == "error":
            running.error = "执行失败（" + str(data.get("code", "AgentError"))[:80] + "），请检查配置、网络或工具。"
            if data.get("code") in {"OpenAITimeoutError", "APITimeoutError"}:
                running.error = "模型服务未在请求时限内返回，本次执行已停止。可重试，原执行记录会保留。"
            if data.get("code") == "CheckpointError":
                running.error = redact(str(data.get("message", "checkpoint 无法恢复")))[:500]
        elif kind == "snapshot":
            running.snapshot = json.loads(redact(json.dumps(data, ensure_ascii=False)))
        elif kind in {"model", "tool_start", "tool_end", "plan", "subagent_start", "subagent_end", "subgraph"}:
            safe = json.loads(redact(json.dumps(data, ensure_ascii=False)))
            record_event(running.attempt.pk, running.attempt.claim_token, kind, safe)


def run_worker(*, concurrency: int, timeout: int, once: bool = False, max_jobs: int | None = None) -> None:
    require_postgres()
    worker_id = uuid.uuid4()
    running: list[Running] = []
    stopping = False
    completed = 0
    last_sweep = 0.0

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    old_signals = {sig: signal.signal(sig, stop) for sig in [signal.SIGTERM, signal.SIGINT]}
    try:
        while not stopping:
            close_old_connections()
            expire_leases()
            reconcile_interrupted()
            if time.monotonic() - last_sweep > 5:
                from personal_superagent.devices.protocol import sweep
                sweep()
                from personal_superagent.collaboration.routing import dispatch_pending
                from personal_superagent.knowledge.services import schedule_due
                dispatch_pending()
                schedule_due()
                last_sweep = time.monotonic()
            for item in list(running):
                consume(item)
                current = Attempt.objects.get(pk=item.attempt.pk)
                expired = not heartbeat(current.pk, item.attempt.claim_token)
                timed_out = time.monotonic() - item.started >= min(timeout,current.input_snapshot.get("policy",{}).get("timeout",timeout))
                if expired or current.cancel_requested_at or timed_out or item.error:
                    terminate(item.process)
                    item.error = item.error or ("执行超时" if timed_out else "执行被取消或领取已失效")
                if item.process.poll() is not None:
                    # 等待读线程把退出前的最后一条结果交回来。
                    consume(item)
                    if not item.eof:
                        continue
                    snapshot = item.snapshot if item.process.returncode == 0 and not item.error else None
                    success = item.process.returncode == 0 and bool(item.result or snapshot) and not item.error
                    complete(current.pk, item.attempt.claim_token,
                             state="succeeded" if success else "failed", result=item.result if success else "",
                             error=item.error or ("" if success else "执行进程异常退出或未交付结果"), snapshot=snapshot)
                    item.process.stdin.close()
                    item.process.stdout.close()
                    running.remove(item)
                    completed += 1
            while len(running) < concurrency and not stopping and (max_jobs is None or completed + len(running) < max_jobs):
                attempt = claim_next(worker_id)
                if attempt is None:
                    break
                try:
                    item = spawn(attempt)
                    if item:
                        running.append(item)
                except Exception:
                    complete(attempt.pk, attempt.claim_token, state="failed", error="无法启动执行子进程")
                    completed += 1
            if max_jobs is not None and completed >= max_jobs:
                break
            if once and not running:
                break
            time.sleep(0.2)
    finally:
        for item in running:
            terminate(item.process)
            complete(item.attempt.pk, item.attempt.claim_token, state="interrupted", error="Worker 正常关闭，执行未自动重试")
            item.process.stdin.close()
            item.process.stdout.close()
        for sig, handler in old_signals.items():
            signal.signal(sig, handler)
