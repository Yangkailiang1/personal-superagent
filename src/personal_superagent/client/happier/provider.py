"""CC Switch 仅在本机解析；公开配置指纹用于冻结，不发送凭据。"""

import json
import subprocess
import tempfile
import uuid
from pathlib import Path


def info(executor):
    script = "import('./dist/provider.js').then(m=>{const p=m.loadProvider();console.log(JSON.stringify({configured:p.configured,model:p.model,fingerprint:p.fingerprint}))})"
    p = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=executor.parent.parent,
        capture_output=True,
        timeout=15,
        check=True,
    )
    return json.loads(p.stdout)


def verify(executor):
    config = info(executor)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        sentinel = uuid.uuid4().hex
        (root / "probe.txt").write_text(sentinel)
        p = subprocess.Popen(
            ["node", str(executor)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        p.stdin.write(
            json.dumps(
                {
                    "protocol": 1,
                    "action": "start",
                    "cwd": str(root),
                    "prompt": "Read probe.txt with the Read tool, then return its exact contents. Do not perform other operations.",
                    "write_paths": [],
                    "checks": [],
                    "max_turns": 3,
                    "provider_fingerprint": config["fingerprint"],
                }
            )
            + "\n"
        )
        p.stdin.flush()
        import threading

        events = []

        def read():
            for line in p.stdout:
                events.append(json.loads(line))

        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        from .worker import stop

        try:
            p.wait(timeout=100)
        finally:
            stop(p)
        thread.join(timeout=2)
        results = [e for e in events if e.get("kind") == "result"]
        if (
            not results
            or sentinel not in results[-1].get("text", "")
            or not any(
                e.get("kind") == "tool_end" and not e.get("failed") for e in events
            )
        ):
            raise ValueError("真实模型工具调用验证失败")
    return config
