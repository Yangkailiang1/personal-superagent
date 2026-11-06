"""隔离 PostgreSQL + Chromium + 本机 Node 协议夹具，不调用真实 Claude。"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import patch
import psycopg
from playwright.sync_api import sync_playwright, expect

PROJECT = Path(__file__).resolve().parents[1]
name = "qa_v07_" + uuid.uuid4().hex[:12]
admin = psycopg.connect(dbname=os.environ["PGDATABASE"], autocommit=True)
admin.execute("CREATE DATABASE " + name)
os.environ["PGDATABASE"] = name
os.environ["DJANGO_ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"
server = None
try:
    import django

    django.setup()
    from django.core.management import call_command

    call_command("migrate", verbosity=0)
    from django.contrib.auth import get_user_model
    from personal_superagent.devices.auth import pair, new_pairing
    from personal_superagent.happier.services import hello, claim
    from personal_superagent.happier.models import Repository
    from personal_superagent.collaboration.models import AgentProfile
    from personal_superagent.collaboration.routing import dispatch_pending
    from personal_superagent.collaboration.tests import PLAN
    from personal_superagent.intake.models import Conversation
    from personal_superagent.tasks.models import Task
    from personal_superagent.client.happier import repositories, worker
    from personal_superagent.client.happier.ledger import Ledger

    password = uuid.uuid4().hex
    user = get_user_model().objects.create_user("v07-browser", password=password)
    device, token = pair(new_pairing(user), "V0.7 测试设备")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "client"
        root.mkdir(mode=0o700)
        repo = Path(temporary) / "repository"
        repo.mkdir()

        def git(*args):
            subprocess.run(
                ["git", "-C", str(repo), *args], check=True, capture_output=True
            )

        git("init")
        git("config", "user.name", "QA")
        git("config", "user.email", "qa@example.invalid")
        (repo / "base.txt").write_text("base")
        git("add", ".")
        git("commit", "-m", "baseline")
        item = repositories.register(
            root, "协议夹具仓库", repo, ["src"], ["git status --short"], "HEAD"
        )
        hello(device, {"ready": True, "repositories": repositories.manifest(root)})
        c = Conversation.objects.create(
            owner=user,
            plan_mode=True,
            title="V0.7 协议夹具（非真实模型）",
            draft={**PLAN, "steps": [PLAN["steps"][0]]},
        )
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        log = (PROJECT / ".artifacts/v07-browser-server.log").open("w")
        server = subprocess.Popen(
            [
                sys.executable,
                "manage.py",
                "runserver",
                f"127.0.0.1:{port}",
                "--noreload",
            ],
            cwd=PROJECT,
            env=os.environ.copy(),
            stdout=log,
            stderr=log,
        )
        config = {"url": url, "device_id": str(device.pk), "token": token, "roots": []}

        def execute():
            from django.db import connections

            try:
                dispatch_pending()
                job = claim(device)["job"]
                if not job:
                    raise AssertionError("No queued job")
                ledger = Ledger(root)
                try:
                    with patch.object(
                        worker,
                        "EXECUTOR",
                        PROJECT / "tests/fixtures/claude-recorded-executor.mjs",
                    ):
                        worker.execute(root, config, ledger, job)
                finally:
                    ledger.db.close()
            finally:
                connections.close_all()

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, executable_path=p.chromium.executable_path
            )
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            for _ in range(80):
                try:
                    page.goto(url + "/app/?intake=" + str(c.pk))
                    break
                except Exception:
                    time.sleep(0.2)
            page.get_by_label("用户名").fill(user.username)
            page.get_by_label("密码").fill(password)
            page.get_by_role("button", name="登录", exact=True).click()
            page.goto(url + "/app/?intake=" + str(c.pk))
            page.get_by_label("代码仓库 " + PLAN["steps"][0]["key"]).select_option(
                item["id"]
            )
            expect(
                page.get_by_text("低风险及预授权命令自动执行", exact=False)
            ).to_be_visible(timeout=15000)
            page.get_by_role("button", name="发布并执行", exact=True).click()
            expect(
                page.get_by_role("heading", name="任务看板", exact=True)
            ).to_be_visible(timeout=15000)
            thread = threading.Thread(target=execute)
            thread.start()
            task = page.request.get(url + "/api/bootstrap/").json()["tasks"][0]
            page.goto(url + "/app/?view=task&task=" + task["id"])
            button = page.get_by_role("button", name="批准本次", exact=True)
            expect(button).to_be_visible(timeout=20000)
            page.screenshot(
                path=str(PROJECT / ".artifacts/v07-approval.png"), full_page=True
            )
            button.click()
            thread.join(timeout=20)
            assert not thread.is_alive()
            page.reload()
            expect(
                page.get_by_role("button", name="下载交付报告", exact=True)
            ).to_be_visible(timeout=15000)
            expect(page.get_by_text("退出码 0", exact=False)).to_be_visible()
            page.get_by_text("src/result.txt", exact=True).click()
            expect(page.get_by_text("recorded output", exact=True)).to_be_visible()
            page.screenshot(
                path=str(PROJECT / ".artifacts/v07-delivery.png"), full_page=True
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.reload()
            expect(
                page.get_by_role("button", name="下载交付报告", exact=True)
            ).to_be_visible()
            assert not errors, errors
            browser.close()
            print(
                "PASS: Chromium Plan selection → publish → HTTP/Node approval → result/checks → refresh/mobile; recorded provider only"
            )
finally:
    if server:
        server.terminate()
        server.wait(timeout=10)
    from django.db import connections

    connections.close_all()
    admin.execute("DROP DATABASE " + name + " WITH (FORCE)")
    admin.close()
