"""专用账号验收：需求对话 → 草稿确认 → 执行 → 看板与追溯，不调用付费模型。"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

url = os.environ.get("BROWSER_TEST_URL", "http://127.0.0.1:18005/app/")
origin = urlsplit(url).scheme + "://" + urlsplit(url).netloc
credentials = json.loads(Path(os.environ["BROWSER_TEST_CREDENTIALS"]).read_text())


def worker():
    if os.environ.get("BROWSER_MANAGED_WORKER") == "1":
        return
    p = subprocess.run(
        [sys.executable, "manage.py", "agent_worker", "--once"],
        capture_output=True,
        timeout=60,
    )
    assert p.returncode == 0, p.stderr.decode()


with sync_playwright() as p:
    executable = os.environ.get("CHROMIUM_EXECUTABLE")
    browser = p.chromium.launch(
        headless=True, **({"executable_path": executable} if executable else {})
    )
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    page.get_by_label("用户名").fill(credentials["BROWSER_TEST_USER"])
    page.get_by_label("密码").fill(credentials["BROWSER_TEST_PASSWORD"])
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page.get_by_role("heading", name="任务看板", exact=True)).to_be_visible(
        timeout=60000
    )
    expect(page.get_by_text("云端已连接", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="需求对话", exact=True).click()
    page.get_by_label("需求消息").fill("整理一份每周学习计划，并明确验收标准。")
    page.get_by_role("button", name="发送", exact=True).click()
    worker()
    expect(page.get_by_label("任务名称")).to_have_value("需求整理", timeout=60000)
    page.screenshot(path=".artifacts/v05-intake.png", full_page=True)
    page.get_by_role("button", name="任务看板", exact=True).click()
    expect(page.locator(".kanban-card").filter(has_text="草稿")).to_be_visible(
        timeout=15000
    )
    page.locator(".kanban-card").filter(has_text="草稿").click()
    page.get_by_role("button", name="确认生成任务", exact=True).click()
    expect(page.get_by_role("button", name="启动", exact=True)).to_be_visible(
        timeout=15000
    )
    task_id = page.url.split("task=")[1]
    page.get_by_role("button", name="启动", exact=True).click()
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        worker()
        page.wait_for_timeout(1800)
        d = page.request.get(origin + "/api/task/?id=" + task_id, max_retries=3).json()
        state = d["state"]
        if state == "waiting_approval":
            expect(page.get_by_role("button", name="批准", exact=True)).to_be_visible(
                timeout=20000
            )
            page.get_by_role("button", name="批准", exact=True).click()
        elif state == "succeeded":
            break
        elif state in {"failed", "interrupted", "cancelled"}:
            raise AssertionError(d)
    expect(page.locator(".task-header .status")).to_have_text("执行完成", timeout=20000)
    page.get_by_role("button", name="来源与历史", exact=True).click()
    expect(page.get_by_role("link", name="需求对话", exact=True)).to_be_visible()
    expect(page.get_by_label("历史执行")).to_be_visible()
    page.get_by_role("button", name="任务看板", exact=True).click()
    expect(page.get_by_test_id("card-" + task_id)).to_be_visible(
        timeout=15000
    )
    page.screenshot(path=".artifacts/v05-dashboard.png", full_page=True)
    page.reload()
    expect(page.get_by_role("heading", name="任务看板", exact=True)).to_be_visible(
        timeout=60000
    )
    expect(page.get_by_test_id("card-" + task_id)).to_be_visible(
        timeout=20000
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=".artifacts/v05-mobile.png", full_page=True)
    assert not errors, errors
    browser.close()
print(
    "PASS: V0.5 需求会话、原生图草稿、确认入队、审批交付、Dashboard、来源历史、刷新与手机布局。"
)
