"""先落盘再上传；进程崩溃不能把一个有副作用的任务当成尚未执行。"""

import json
import sqlite3


class Ledger:
    def __init__(self, root):
        self.db = sqlite3.connect(root / "happier.sqlite3")
        self.db.execute("pragma journal_mode=WAL")
        self.db.execute(
            "create table if not exists jobs(id text primary key, job text not null, pid integer, birth real, result text)"
        )
        self.db.execute(
            "create table if not exists events(job text, sequence integer, event text, primary key(job,sequence))"
        )
        self.db.execute(
            "create table if not exists cursors(job text primary key, seq integer)"
        )
        self.db.execute("create table if not exists receipts(job text primary key)")
        self.db.commit()

    def begin(self, job):
        self.db.execute(
            "insert into jobs(id,job) values(?,?)", (job["id"], json.dumps(job))
        )
        self.db.commit()

    def process(self, id, pid, birth):
        self.db.execute("update jobs set pid=?,birth=? where id=?", (pid, birth, id))
        self.db.commit()

    def event(self, id, event):
        seq = self.db.execute(
            "select coalesce(max(sequence),0)+1 from events where job=?", (id,)
        ).fetchone()[0]
        self.db.execute(
            "insert into events values(?,?,?)", (id, seq, json.dumps(event))
        )
        self.db.commit()

    def finish(self, id, result):
        self.db.execute("update jobs set result=? where id=?", (json.dumps(result), id))
        self.db.commit()

    def unfinished(self):
        return self.db.execute(
            "select id,job,pid,birth,result from jobs where id not in(select job from receipts)"
        ).fetchall()

    def ack(self, id):
        self.db.execute("insert or ignore into receipts values(?)", (id,))
        self.db.commit()
