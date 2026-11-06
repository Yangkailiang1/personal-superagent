"""事件回执落盘后发送，心跳独立于模型输出和大图片上传。"""

import json
import base64
import threading
import time
from .agent import request, manifest
from .config import load


class Heartbeat:
    def __init__(self, root, job, process):
        self.root = root
        self.job = job
        self.process = process
        self.stop = threading.Event()
        self.denied = False

    def __enter__(self):
        def beat():
            deadline = time.monotonic() + self.job["snapshot"]["policy"]["timeout"]
            while not self.stop.is_set():
                try:
                    config = load(self.root)
                    data = request(
                        config,
                        "agent-control",
                        {
                            "id": self.job["id"],
                            "token": self.job["token"],
                            "action": "heartbeat",
                            "grants": manifest(config),
                        },
                    )
                    if not data["continue"] or time.monotonic() > deadline:
                        raise ValueError("许可失效")
                except Exception:
                    self.denied = True
                    if self.process.poll() is None:
                        self.process.terminate()
                    return
                self.stop.wait(3)

        self.thread = threading.Thread(target=beat, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(16)


def init_events(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS outbox(token TEXT, sequence INTEGER, body TEXT, PRIMARY KEY(token,sequence))"
    )
    db.commit()


def flush_events(db, config, token):
    for sequence, body in db.execute(
        "SELECT sequence,body FROM outbox WHERE token=? ORDER BY sequence", (token,)
    ).fetchall():
        request(config, "agent-control", json.loads(body))
        db.execute("DELETE FROM outbox WHERE token=? AND sequence=?", (token, sequence))
        db.commit()


def redact(root, data):
    encoded = json.dumps(data, ensure_ascii=False)
    for filename in ["model.json", "client.json"]:
        try:
            config = json.loads((root / filename).read_text())
        except OSError:
            continue
        for key, value in config.items():
            if (
                (key.endswith("KEY") or key == "token")
                and isinstance(value, str)
                and len(value) >= 8
            ):
                encoded = encoded.replace(value, "[REDACTED]")
    return json.loads(encoded)


def event(db, config, token, sequence, body):
    db.execute(
        "INSERT OR IGNORE INTO outbox VALUES (?,?,?)",
        (token, sequence, json.dumps(body)),
    )
    db.commit()
    flush_events(db, config, token)


def deliver(root, config, job, result):
    for image in result.get("snapshot", {}).get("images", []):
        path = root / "runs" / job["id"] / "images" / image["name"]
        if path.name != image["name"] or path.is_symlink():
            raise ValueError("图片路径无效")
        request(
            config,
            "agent-control",
            {
                "id": job["id"],
                "token": job["token"],
                "action": "image",
                "name": image["name"],
                "content": base64.b64encode(path.read_bytes()).decode(),
            },
        )
    request(
        config,
        "agent-control",
        {"id": job["id"], "token": job["token"], "action": "result", "result": result},
    )
