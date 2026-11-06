"""已部署服务器 + 本机 Node 夹具；需要独立 QA 账号和 SSH 隧道，不调用模型。"""

import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from personal_superagent.client.agent import request
from personal_superagent.client.happier import repositories, worker
from personal_superagent.client.happier.ledger import Ledger

PROJECT = Path(__file__).resolve().parents[1]
url = os.environ.get("BROWSER_TEST_ORIGIN", "http://127.0.0.1:18006")
credentials = json.loads((PROJECT / ".artifacts/remote-qa.json").read_text())
with tempfile.TemporaryDirectory() as temporary, sync_playwright() as p:
    root = Path(temporary) / "client"
    root.mkdir(mode=0o700)
    repo = Path(temporary) / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init")
    git("config", "user.name", "QA")
    git("config", "user.email", "qa@example.invalid")
    (repo / "base.txt").write_text("base")
    git("add", ".")
    git("commit", "-m", "base")
    item = repositories.register(
        root, "服务器协议夹具仓库", repo, ["src"], ["git status --short"], "HEAD"
    )
    item["policy"]["timeout"] = 60
    item["policy"]["max_turns"] = 4
    repositories.save(root, [item])
    browser = p.chromium.launch(
        headless=True, executable_path=p.chromium.executable_path
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.goto(url + "/app/")
    page.get_by_label("用户名").fill(credentials["BROWSER_TEST_USER"])
    page.get_by_label("密码").fill(credentials["BROWSER_TEST_PASSWORD"])
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page.get_by_role("heading", name="主对话", exact=True)).to_be_visible(
        timeout=20000
    )
    csrf = next(c["value"] for c in page.context.cookies() if c["name"] == "csrftoken")

    def post(path, data):
        response = page.request.post(
            url + path, data=data, headers={"X-CSRFToken": csrf}
        )
        assert response.ok, (path, response.status)
        return response.json()

    pairing = post("/api/pairing/", {})
    config = {
        "url": url,
        "roots": [],
        **request(
            {"url": url},
            "pair",
            {"code": pairing["code"], "name": "V0.7 固定协议测试设备"},
        ),
    }
    request(
        config,
        "happier-hello",
        {"ready": True, "repositories": repositories.manifest(root)},
    )
    binding = page.request.get(url + "/api/happier/repositories/").json()["items"][0]
    conversation = post("/api/intake/conversations/", {"style": "plan"})
    plan = {
        "title": "V0.7 服务器协议验收（非真实模型）",
        "goal": "验证本机派发与审批回收",
        "materials": "固定协议夹具",
        "deliverables": ["src/result.txt"],
        "acceptance": ["有文件和检查证据"],
        "questions": [],
        "assumptions": [],
        "device_needs": "明确绑定本机",
        "steps": [
            {
                "key": "code",
                "title": "固定协议夹具任务（非真实模型）",
                "goal": "验证执行层通信，禁止真实模型调用",
                "role": "coder",
                "tools": ["repository_write", "repository_command"],
                "agent_id": binding["agent_id"],
                "repository_id": binding["id"],
                "repository_version": binding["version"],
                "base_commit": binding["baseline"],
                "write_paths": ["src"],
                "checks": ["git status --short"],
                "depends_on": [],
                "deliverables": ["src/result.txt"],
                "acceptance": ["回收输出和检查"],
            }
        ],
    }
    post("/api/intake/edit/", {"id": conversation["id"], "version": 1, "draft": plan})
    page.goto(url + "/app/?intake=" + conversation["id"])
    expect(page.get_by_role("button", name="发布并执行", exact=True)).to_be_visible()
    page.get_by_role("button", name="发布并执行", exact=True).click()
    expect(page.get_by_role("heading", name="任务看板", exact=True)).to_be_visible()
    stop = threading.Event()
    errors = []

    def run_client():
        ledger = Ledger(root)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not stop.is_set():
                request(
                    config,
                    "happier-hello",
                    {"ready": True, "repositories": repositories.manifest(root)},
                )
                job = request(config, "happier-claim", {})["job"]
                if job:
                    with patch.object(
                        worker,
                        "EXECUTOR",
                        PROJECT / "tests/fixtures/claude-recorded-executor.mjs",
                    ):
                        worker.execute(root, config, ledger, job)
                    return
                time.sleep(1)
            raise AssertionError("服务器未派发任务")
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
        finally:
            ledger.db.close()

    thread = threading.Thread(target=run_client)
    thread.start()
    try:
        task = page.request.get(url + "/api/bootstrap/").json()["tasks"][0]
        page.goto(url + "/app/?view=task&task=" + task["id"])
        button = page.get_by_role("button", name="批准本次", exact=True)
        expect(button).to_be_visible(timeout=30000)
        page.screenshot(
            path=str(PROJECT / ".artifacts/v07-server-approval.png"), full_page=True
        )
        button.click()
        thread.join(timeout=25)
        assert not thread.is_alive() and not errors, errors
        page.reload()
        expect(
            page.get_by_role("button", name="下载交付报告", exact=True)
        ).to_be_visible(timeout=20000)
        expect(page.get_by_text("退出码 0", exact=False)).to_be_visible()
        with page.expect_download() as download:
            page.get_by_role("button", name="下载交付报告", exact=True).click()
        output = json.loads(Path(download.value.path()).read_text())
        assert output["files"][0]["content"] == "recorded output"
        assert output["checks"][0]["exit_code"] == 0
        page.screenshot(
            path=str(PROJECT / ".artifacts/v07-server-delivery.png"), full_page=True
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.reload()
        expect(
            page.get_by_role("button", name="下载交付报告", exact=True)
        ).to_be_visible()
        assert (repo / "base.txt").read_text() == "base" and not (repo / "src").exists()
        print(
            "PASS: server Plan→device dispatch→Node fixture→browser approval→Git check→delivery download/refresh/mobile; no model call"
        )
    finally:
        stop.set()
        thread.join(timeout=70)
        browser.close()
