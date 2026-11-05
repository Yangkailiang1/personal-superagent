"""本地或 SSH 隧道真实浏览器验收；只使用专用临时账号，不调用付费模型。"""
import os
import shlex
import subprocess
import sys
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def process_queue():
    if os.environ.get("BROWSER_MANAGED_WORKER") == "1":
        return
    result = subprocess.run([sys.executable, "manage.py", "agent_worker", "--once"], capture_output=True, timeout=45)
    assert result.returncode == 0, "Worker 执行失败"


with sync_playwright() as p:
    credentials = json.loads(Path(os.environ["BROWSER_TEST_CREDENTIALS"]).read_text()) if os.environ.get("BROWSER_TEST_CREDENTIALS") else os.environ
    executable = os.environ.get("CHROMIUM_EXECUTABLE")
    browser = p.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))
    context = browser.new_context(viewport={"width": 1280, "height": 1000}, accept_downloads=True)
    page = context.new_page()
    page.goto(os.environ.get("BROWSER_TEST_URL", "http://127.0.0.1:8002/"))
    page.get_by_label("用户名").fill(credentials["BROWSER_TEST_USER"])
    page.get_by_label("密码").fill(credentials["BROWSER_TEST_PASSWORD"])
    page.get_by_role("button", name="登录", exact=True).click()
    for decision in ["批准保存", "拒绝保存", "取消执行"]:
        page.get_by_label("任务名称").fill("V0.3 验收 · " + decision)
        page.get_by_label("任务需求").fill("每周阅读两小时，请把需求整理成计划，检查遗漏，生成一份文档。")
        page.get_by_role("button", name="保存任务").click()
        page.get_by_role("button", name="启动任务", exact=True).click()
        process_queue()
        expect(page.locator("#state")).to_have_text("待审批", timeout=45000)
        expect(page.get_by_role("button", name="批准保存", exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_role("button", name="批准保存", exact=True)).to_be_visible()
        expect(page.get_by_text("任务与结果", exact=True)).to_have_count(2)
        expect(page.get_by_role("link", name="任务整理.md", exact=True)).to_have_count(0)
        expect(page.locator("#subtasks")).to_contain_text("writer")
        expect(page.locator("#subtasks")).to_contain_text("reviewer")
        if decision == "批准保存":
            if os.environ.get("BROWSER_RESTART_COMMAND"):
                result = subprocess.run(shlex.split(os.environ["BROWSER_RESTART_COMMAND"]), timeout=45, capture_output=True)
                assert result.returncode == 0, "服务重启失败"
                page.wait_for_timeout(1500)
                page.reload()
                expect(page.locator("#state")).to_have_text("待审批")
            Path(".artifacts").mkdir(exist_ok=True)
            page.screenshot(path=".artifacts/v03-approval.png", full_page=True)
        page.get_by_role("button", name=decision, exact=True).click()
        if decision != "取消执行":
            process_queue()
            expect(page.locator("#state")).to_have_text("成功", timeout=45000)
            expect(page.locator("#result h2")).to_be_visible()
        else:
            expect(page.locator("#state")).to_have_text("已取消")
        if decision == "批准保存":
            with page.expect_download() as captured:
                page.get_by_role("link", name="下载", exact=True).click()
            assert captured.value.suggested_filename == "任务整理.md"
            assert Path(captured.value.path()).read_text().startswith("# ")
            page.get_by_role("link", name="任务整理.md", exact=True).first.click()
            expect(page.get_by_role("heading", name="任务整理草稿", exact=True)).to_be_visible()
            page.screenshot(path=".artifacts/v03-artifact.png", full_page=True)
            page.get_by_role("link", name="返回任务", exact=True).click()
        else:
            expect(page.get_by_role("link", name="任务整理.md", exact=True)).to_have_count(0)
        page.get_by_role("link", name="返回任务列表").click()
    page.get_by_role("button", name="退出", exact=True).click()
    browser.close()
    print("PASS: 多 Agent、计划、审批刷新恢复、批准与下载、拒绝不发布、取消审批、Markdown。")
