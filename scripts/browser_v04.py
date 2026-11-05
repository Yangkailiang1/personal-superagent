"""真实浏览器 + 本机客户端验收。临时目录以外不授权，演示不调用付费模型。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

url = os.environ.get("BROWSER_TEST_URL", "http://127.0.0.1:8002/app/")
origin = urlsplit(url).scheme + "://" + urlsplit(url).netloc
credentials = json.loads(Path(os.environ["BROWSER_TEST_CREDENTIALS"]).read_text()) if os.environ.get("BROWSER_TEST_CREDENTIALS") else os.environ


def worker():
    if os.environ.get("BROWSER_MANAGED_WORKER") == "1": return
    result = subprocess.run([sys.executable, "manage.py", "agent_worker", "--once"], capture_output=True, timeout=50)
    assert result.returncode == 0, "Worker 执行失败"


with tempfile.TemporaryDirectory() as folder, sync_playwright() as p:
    root = Path(folder); materials = root / "materials"; materials.mkdir()
    (materials / "input.md").write_text("# 本地需求\nBROWSER_LOCAL_SENTINEL_40：整理个人学习计划。")
    def cli(*args):
        result = subprocess.run([sys.executable,"-m","personal_superagent.client.cli","--config-dir",str(root/"client"),*args],capture_output=True,timeout=35)
        assert result.returncode == 0, result.stdout.decode()+result.stderr.decode()
    executable = os.environ.get("CHROMIUM_EXECUTABLE")
    browser = p.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))
    context = browser.new_context(viewport={"width":1440,"height":1000}, accept_downloads=True)
    page = context.new_page(); errors=[]; page.on("pageerror",lambda error: errors.append(str(error)))
    page.goto(url)
    page.get_by_label("用户名").fill(credentials["BROWSER_TEST_USER"])
    page.get_by_label("密码").fill(credentials["BROWSER_TEST_PASSWORD"])
    page.get_by_role("button",name="登录",exact=True).click()
    try:
        expect(page.get_by_role("heading",name="把想法交给工作台")).to_be_visible(timeout=30000)
    except AssertionError:
        print("Browser diagnostics:",page.url,errors,page.locator("body").inner_text()[:800])
        raise
    Path(".artifacts").mkdir(exist_ok=True)
    page.screenshot(path=".artifacts/v04-home.png",full_page=True)
    page.get_by_role("button",name="设备与授权",exact=True).click()
    page.get_by_role("button",name="绑定设备",exact=True).click()
    code=page.locator(".pairing-box > code").inner_text()
    cli("pair","--url",origin,"--code",code,"--name","浏览器验收电脑")
    cli("grant","--name","演示笔记","--path",str(materials),"--tools","list_files,read_text,write_text","--ack-cloud-transfer")
    cli("run","--once")
    expect(page.get_by_role("heading",name="浏览器验收电脑")).to_be_visible(timeout=15000)
    expect(page.locator(".grant")).to_contain_text("演示笔记")
    page.get_by_role("button",name="收起",exact=True).click()
    page.screenshot(path=".artifacts/v04-devices.png",full_page=True)
    page.get_by_role("button",name="工作台",exact=True).click()
    page.get_by_label("授权目录").select_option(label="浏览器验收电脑 / 演示笔记")
    page.get_by_label("任务需求").fill("读取授权的本地材料，整理为学习计划，检查并保存结果。")
    page.get_by_role("button",name="创建任务",exact=True).click()
    expect(page.get_by_role("button",name="启动",exact=True)).to_be_visible()
    page.get_by_role("button",name="启动",exact=True).click()
    task_id = page.url.split("task=")[1]
    approved=False
    for _ in range(16):
        worker()
        page.wait_for_timeout(1600)
        data=page.request.get(origin+"/api/task/?id="+task_id,max_retries=3).json()
        state=data["state"]
        if state=="queued": continue
        if state=="waiting_device":
            cli("run","--once")
        elif state=="waiting_approval":
            expect(page.get_by_role("button",name="批准",exact=True)).to_be_visible(timeout=15000)
            if not approved:
                assert not (materials/"superagent-result.md").exists()
                page.screenshot(path=".artifacts/v04-approval.png",full_page=True)
                approved=True
            page.get_by_role("button",name="批准",exact=True).click()
        elif state=="succeeded": break
        elif state in {"failed","interrupted","cancelled"}: raise AssertionError(str(data))
    expect(page.locator(".task-header .status")).to_have_text("执行完成",timeout=20000)
    assert "BROWSER_LOCAL_SENTINEL_40" in (materials/"superagent-result.md").read_text()
    assert data["attempt"]["artifacts"]
    page.get_by_role("button",name="执行过程",exact=True).click()
    expect(page.locator(".process-view")).to_contain_text("读取文本")
    page.screenshot(path=".artifacts/v04-process.png",full_page=True)
    page.get_by_role("button",name="交付物",exact=True).click()
    with page.expect_popup() as popup:
        page.get_by_role("link",name="任务整理.md",exact=False).click()
    preview=popup.value
    expect(preview.locator("article")).to_contain_text("BROWSER_LOCAL_SENTINEL_40")
    with preview.expect_download() as download:
        preview.get_by_role("link",name="下载 Markdown").click()
    assert "BROWSER_LOCAL_SENTINEL_40" in Path(download.value.path()).read_text()
    preview.close()
    page.reload(); expect(page.locator(".task-header .status")).to_have_text("执行完成")
    page.set_viewport_size({"width":390,"height":844}); page.reload()
    expect(page.get_by_role("button",name="切换侧栏")).to_be_visible()
    expect(page.locator(".task-header .status")).to_have_text("执行完成",timeout=15000)
    page.screenshot(path=".artifacts/v04-mobile.png",full_page=True)
    assert not errors, errors
    browser.close()
    print("PASS: assistant-ui 桌面/手机、设备绑定、授权同步、真实文件读取、审批后新建、云端产物与字节下载、刷新。")
