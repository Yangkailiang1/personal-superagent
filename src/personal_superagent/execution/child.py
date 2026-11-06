"""子进程协议：stdin 首行输入，其余连接用于存活检测；stdout 是 JSONL。"""
import json
import os
import sys
import threading

OUTPUT_LOCK = threading.Lock()


def emit(kind: str, data: dict) -> None:
    with OUTPUT_LOCK:
        print(json.dumps({"kind": kind, "data": data}, ensure_ascii=False), flush=True)


def watch_parent() -> None:
    # Worker 被 SIGKILL 后管道关闭，即使模型请求阻塞也退出；不依赖 PID 判断父身份。
    # 直接读 fd，避免 daemon 在解释器退出时占住 BufferedReader 锁导致崩溃。
    os.read(sys.stdin.fileno(), 1)
    os._exit(75)


def main() -> None:
    os.umask(0o077)
    payload = json.loads(sys.stdin.buffer.readline())
    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        if payload["snapshot"].get("kind") == "intake":
            from personal_superagent.intake.agent import run_intake
            emit("result", {"text": run_intake(payload["snapshot"], payload["mode"], emit)})
        elif payload.get("workflow_version"):
            from personal_superagent.workflow.versions import module_for
            data = module_for(payload["workflow_version"]).run_workflow(payload, emit)
            emit("snapshot", data)
        else:
            from .agent import run_agent
            result = run_agent(payload["snapshot"], payload["mode"], emit)
            emit("result", {"text": result})
    except Exception as exc:
        # 原始供应商异常可能包含请求信息，不进入 stdout / DB / 日志。
        message = str(exc) if type(exc).__name__ == "CheckpointError" else "执行失败，请检查模型配置、网络与工具能力。"
        emit("error", {"code": type(exc).__name__, "message": message[:500]})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
