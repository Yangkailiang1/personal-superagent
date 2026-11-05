"""对已启动的本地服务验收；账号由环境提供，不创建默认密码。"""
import os
from pathlib import Path
import subprocess
import sys

from playwright.sync_api import sync_playwright, expect


def worker():
    process = subprocess.run([sys.executable, "manage.py", "agent_worker", "--once"], capture_output=True, timeout=40)
    assert process.returncode == 0, "Worker 未正常完成，请查看自动测试和配置。"


with sync_playwright() as p:
    executable = os.environ.get("CHROMIUM_EXECUTABLE")
    browser = p.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.goto(os.environ.get("BROWSER_TEST_URL", "http://127.0.0.1:8002/"))
    page.get_by_label("用户名").fill(os.environ["BROWSER_TEST_USER"])
    page.get_by_label("密码").fill(os.environ["BROWSER_TEST_PASSWORD"])
    page.get_by_role("button", name="登录").click()
    page.get_by_label("任务名称").fill("V0.2 浏览器验收")
    page.get_by_label("任务需求").fill("请通过工具统计本次任务文本。")
    page.get_by_role("button", name="保存任务").click()
    task_url = page.url
    page.get_by_role("button", name="启动任务", exact=True).click()
    expect(page.locator("#state")).to_have_text("排队中")
    page.reload()
    expect(page.locator("#state")).to_have_text("排队中")
    # 关掉任务页面后再启动独立 Worker；任务依然完成，页面不拥有执行生命周期。
    page.close()
    worker()
    page = context.new_page()
    page.goto(task_url)
    expect(page.locator("#state")).to_have_text("成功")
    expect(page.locator("#result")).to_contain_text("离线演示")
    page.get_by_text("执行过程", exact=True).click()
    expect(page.locator("#events")).to_contain_text("tool_end")
    Path(".artifacts").mkdir(exist_ok=True)
    page.screenshot(path=".artifacts/v02-success.png", full_page=True)

    page.get_by_role("link", name="返回任务列表").click()
    page.get_by_label("任务名称").fill("V0.2 取消与重试")
    page.get_by_label("任务需求").fill("测试取消与保留历史。")
    page.get_by_role("button", name="保存任务").click()
    page.get_by_role("button", name="启动任务", exact=True).click()
    page.get_by_role("button", name="取消执行", exact=True).click()
    expect(page.locator("#state")).to_have_text("已取消")
    page.get_by_role("button", name="新建执行并重试").click()
    worker()
    # 保持页面打开，验证轮询自己收敛到完成，而不是仅靠主动刷新。
    expect(page.locator("#state")).to_have_text("成功", timeout=15000)
    expect(page.locator("#result")).to_contain_text("离线演示")
    page.screenshot(path=".artifacts/v02-retry.png", full_page=True)
    page.get_by_role("button", name="退出", exact=True).click()
    expect(page.get_by_role("button", name="登录", exact=True)).to_be_visible()
    browser.close()
    print("PASS: 登录、任务创建、启动、刷新、关闭页面后完成、过程事件、取消、重试、轮询、退出。")
