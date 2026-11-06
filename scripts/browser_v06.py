"""浏览器真实 Plan/路由/审批/知识闭环；模型为显式演示，不消耗外部额度。"""

import json, os, subprocess, sys, time
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
    page = browser.new_page(viewport={"width": 1600, "height": 1100})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    page.get_by_label("用户名").fill(credentials["BROWSER_TEST_USER"])
    page.get_by_label("密码").fill(credentials["BROWSER_TEST_PASSWORD"])
    page.get_by_role("button", name="登录", exact=True).click()
    expect(page.get_by_role("heading", name="主对话", exact=True)).to_be_visible(
        timeout=60000
    )
    page.get_by_label("主对话消息").fill("整理学习计划，然后检查交付内容。")
    page.get_by_role("button", name="发送", exact=True).click()
    worker()
    expect(page.get_by_role("button", name="提交选择", exact=True)).to_be_visible(
        timeout=60000
    )
    assert page.locator(".question-card input[type=radio]").count() == 4
    page.locator(".question-card input[type=radio]").nth(3).check()
    page.get_by_label("自行输入回答").fill("输出可执行的学习清单")
    page.screenshot(path=".artifacts/v06-question.png", full_page=True)
    page.get_by_role("button", name="提交选择", exact=True).click()
    worker()
    expect(page.get_by_role("button", name="发布并执行", exact=True)).to_be_visible(
        timeout=60000
    )
    page.reload()
    expect(page.get_by_role("button", name="发布并执行", exact=True)).to_be_visible(
        timeout=60000
    )
    page.screenshot(path=".artifacts/v06-plan.png", full_page=True)
    before = {
        t["id"]
        for t in page.request.get(origin + "/api/bootstrap/", max_retries=3).json()[
            "tasks"
        ]
    }
    page.get_by_role("button", name="发布并执行", exact=True).click()
    expect(page.get_by_role("heading", name="任务看板", exact=True)).to_be_visible(
        timeout=20000
    )
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        worker()
        page.wait_for_timeout(1800)
        tasks = [
            t
            for t in page.request.get(origin + "/api/bootstrap/", max_retries=3).json()[
                "tasks"
            ]
            if t["id"] not in before
        ]
        if len(tasks) == 2 and all(t["state"] == "succeeded" for t in tasks):
            break
        for t in tasks:
            if t["state"] == "waiting_approval":
                page.get_by_test_id("card-" + t["id"]).click()
                expect(
                    page.get_by_role("button", name="批准", exact=True)
                ).to_be_visible(timeout=15000)
                page.get_by_role("button", name="批准", exact=True).click()
                page.get_by_role("button", name="任务看板", exact=True).click()
            elif t["state"] in {"failed", "interrupted"}:
                raise AssertionError(t)
    assert len(tasks) == 2 and all(t["state"] == "succeeded" for t in tasks), tasks
    page.reload()
    for t in tasks:
        expect(page.get_by_test_id("card-" + t["id"])).to_be_visible(timeout=60000)
    page.screenshot(path=".artifacts/v06-dashboard.png", full_page=True)
    page.get_by_role("button", name="知识与长期任务", exact=True).click()
    page.get_by_text("添加只读材料", exact=True).click()
    page.get_by_label("材料标题").fill("验收材料")
    page.get_by_label("材料内容").fill(
        "V06_WIKI_SENTINEL：每周完成两次学习，并保留原始来源。"
    )
    page.get_by_role("button", name="保存原始材料", exact=True).click()
    expect(page.locator(".source-row").last).to_be_visible(timeout=20000)
    page.locator(".source-row input").last.check()
    page.get_by_role("button", name="整理所选材料", exact=True).click()
    worker()
    expect(page.get_by_role("button", name="确认知识修订", exact=True)).to_be_visible(
        timeout=60000
    )
    page.get_by_role("button", name="确认知识修订", exact=True).click()
    page.get_by_label("知识查询").fill("V06_WIKI_SENTINEL")
    page.get_by_role("button", name="查询", exact=True).click()
    expect(page.locator(".knowledge-page")).to_contain_text(
        "V06_WIKI_SENTINEL", timeout=20000
    )
    page.screenshot(path=".artifacts/v06-knowledge.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="主对话", exact=True).click()
    page.screenshot(path=".artifacts/v06-mobile.png", full_page=True)
    assert not errors, errors
    browser.close()
print(
    "PASS: V0.6 四选项、Plan 刷新、发布自动派工、依赖、审批、看板、知识修订与查询、手机布局。"
)
