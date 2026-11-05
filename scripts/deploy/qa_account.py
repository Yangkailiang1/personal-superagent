"""专用临时验收账号；随机密码只存本机忽略目录，验收后删除账号和任务。"""
import json
import secrets
import shlex
import sys
from pathlib import Path

from remote import connect, run

target = Path(".artifacts/remote-qa.json")
if "--delete" in sys.argv:
    data = json.loads(target.read_text())
    if not data["BROWSER_TEST_USER"].startswith("_qa_v03_"):
        raise SystemExit("不是本脚本临时账号，拒绝删除")
    operation = "User.objects.filter(username=data['BROWSER_TEST_USER']).delete(); print('临时验收账号与关联记录已清理')"
else:
    if target.exists():
        raise SystemExit("验收配置已存在，请先清理原临时账号")
    data = {"BROWSER_TEST_USER": "_qa_v03_" + secrets.token_hex(5), "BROWSER_TEST_PASSWORD": secrets.token_urlsafe(24)}
    operation = "User.objects.create_user(username=data['BROWSER_TEST_USER'], password=data['BROWSER_TEST_PASSWORD']); print('已创建临时验收账号（随机密码未输出）')"
code = '''import os, sys, json
from pathlib import Path
for line in Path('/opt/personal-superagent/shared/runtime.env').read_text().splitlines():
    if '=' in line:
        k,v=line.split('=',1); os.environ[k]=v
import django
django.setup()
from django.contrib.auth import get_user_model
User=get_user_model(); data=json.loads(sys.stdin.readline())
''' + operation
with connect() as client:
    status = run(client, "cd /opt/personal-superagent/current && runuser -u superagent -- .venv/bin/python -c " + shlex.quote(code), json.dumps(data) + "\n")
if status:
    raise SystemExit(status)
if "--delete" in sys.argv:
    target.unlink()
else:
    target.parent.mkdir(exist_ok=True)
    with target.open("x") as handle:
        target.chmod(0o600)
        json.dump(data, handle)
