"""副作用前原子扣减；跨子代理、审批恢复及进程重启共享上限。"""

import sqlite3
from pathlib import Path
import os


def spend(directory, name, limit):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = path / "budget.sqlite3"
    with sqlite3.connect(db, timeout=10) as conn:
        os.chmod(db, 0o600)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS usage (name TEXT PRIMARY KEY,n INTEGER NOT NULL)"
        )
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT n FROM usage WHERE name=?", (name,)).fetchone()
        value = row[0] if row else 0
        if value >= limit:
            raise ValueError("本次执行额度已用完：" + name)
        conn.execute(
            "INSERT INTO usage VALUES (?,?) ON CONFLICT(name) DO UPDATE SET n=excluded.n",
            (name, value + 1),
        )
        return value + 1
