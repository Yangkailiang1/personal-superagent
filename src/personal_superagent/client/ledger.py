"""副作用执行前记录 started；崩溃后只报告不确定，绝不把未确认操作重放。"""

import hashlib
import json
import os
import sqlite3


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, digest TEXT, operation TEXT, state TEXT, result TEXT, reported INTEGER DEFAULT 0)"
        )
        self.db.commit()

    def begin(self, operation):
        key = hashlib.sha256(
            json.dumps(
                {k: operation[k] for k in ["grant_id", "tool", "arguments"]},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        with self.db:
            found = self.db.execute(
                "SELECT digest,state,result FROM operations WHERE id=?",
                [operation["id"]],
            ).fetchone()
            if found:
                if found[0] != key:
                    raise ValueError("操作 ID 的参数已改变，拒绝执行")
                return (
                    (found[1], json.loads(found[2]))
                    if found[1] != "started"
                    else ("uncertain", {"error": "旧进程执行结果未知，拒绝重放"})
                )
            self.db.execute(
                "INSERT INTO operations(id,digest,operation,state,result) VALUES(?,?,?,'started','{}')",
                [operation["id"], key, json.dumps(operation)],
            )
        return None

    def complete(self, operation, state, result):
        with self.db:
            self.db.execute(
                "UPDATE operations SET state=?,result=? WHERE id=?",
                [state, json.dumps(result), operation["id"]],
            )

    def pending(self):
        for operation, state, result in self.db.execute(
            "SELECT operation,state,result FROM operations WHERE reported=0"
        ).fetchall():
            yield (
                json.loads(operation),
                ("uncertain" if state == "started" else state),
                (
                    json.loads(result)
                    if state != "started"
                    else {"error": "客户端在操作开始后退出，结果待核实"}
                ),
            )

    def reported(self, operation):
        with self.db:
            self.db.execute(
                "UPDATE operations SET reported=1 WHERE id=?", [operation["id"]]
            )
